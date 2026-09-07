import datetime
import hashlib
import string
import re
import unicodedata
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from prometheus.knowledge_store import KnowledgeStore


class NewsFeed:
    POSITIVE_TERMS = {
        "aprovado",
        "forte",
        "ganho",
        "ganhou",
        "aumento",
        "expansão",
        "recorde",
        "alta",
        "sucesso",
        "otimista",
        "valorização",
        "crescimento",
    }

    NEGATIVE_TERMS = {
        "queda",
        "baixa",
        "retração",
        "perda",
        "recuo",
        "problema",
        "crise",
        "demissão",
        "denúncia",
        "investigação",
        "prejuízo",
        "inadimplência",
        "cai", "caiu", "caem", "desaba", "desabou", "desabam", "derrete", "derreteu", "derretem", "tomba", "tombo",
        "despenca", "despencou", "bloqueia", "bloqueou", "rescisão", "rescisao",
        "cancelamento", "cancelamentos", "queda", "redução", "reducao", "deterioração",
        "deterioracao", "fraude", "suspensão", "suspensao", "multa", "rombo",
    }

    def __init__(self, tickers: List[str], knowledge_store: KnowledgeStore) -> None:
        self.tickers = [t.strip().upper() for t in tickers]
        self.store = knowledge_store
        self._errors: Dict[str, str] = {}

    def _fetch_rss(self, url: str, timeout: int = 10) -> Optional[str]:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; PrometheusNews/1.0)"
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception:
            return None

    def _parse_rss_items(self, rss_bytes: bytes) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        try:
            root = ET.fromstring(rss_bytes)
        except Exception:
            return items

        for item in root.findall('.//item'):
            title_el = item.find('title')
            link_el = item.find('link')
            pub_el = item.find('pubDate')
            if pub_el is None:
                pub_el = item.find('{http://purl.org/dc/elements/1.1/}date')
            source_el = item.find('source')

            title = title_el.text.strip() if title_el is not None and title_el.text else None
            link = link_el.text.strip() if link_el is not None and link_el.text else None
            published_at = None
            if pub_el is not None and pub_el.text:
                try:
                    dt = parsedate_to_datetime(pub_el.text.strip())
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                    published_at = dt.replace(microsecond=0).isoformat() + 'Z'
                except Exception:
                    published_at = None

            source = source_el.text.strip() if source_el is not None and source_el.text else None

            items.append({
                'title': title,
                'url': link,
                'published_at': published_at,
                'source': source,
                'raw': ET.tostring(item, encoding='utf-8').decode('utf-8'),
            })

        return items

    def _score_sentiment(self, text: str) -> float:
        if not text:
            return 50.0

        normalized = unicodedata.normalize("NFKD", text.lower())
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        tokens = re.findall(r"[a-z]+|\d+(?:[.,]\d+)?%?", normalized)
        positive = {unicodedata.normalize("NFKD", term).encode("ascii", "ignore").decode("ascii") for term in self.POSITIVE_TERMS}
        negative = {unicodedata.normalize("NFKD", term).encode("ascii", "ignore").decode("ascii") for term in self.NEGATIVE_TERMS}
        score = 0
        for token in tokens:
            if token in positive:
                score += 1
            elif token in negative:
                score -= 1

        # A percentage collapse is material even when the normalised verb was
        # previously absent from the lexicon.  This remains lexical: it does
        # not assert that a headline is factually correct.
        if any(token in {"cai", "caiu", "queda", "desaba", "desabou", "despenca", "despencou", "tomba", "tombo"} for token in tokens):
            if any(token.endswith("%") for token in tokens):
                score -= 1

        if score == 0:
            return 50.0

        score = max(-5, min(5, score))
        return round(50.0 + score * 10.0, 2)

    def _sentiment_label(self, score: float) -> str:
        if score >= 65:
            return 'POSITIVE'
        if score >= 45:
            return 'NEUTRAL'
        return 'NEGATIVE'

    def collect_ticker(self, ticker: str, as_of: Optional[datetime.datetime] = None, company_name: Optional[str] = None) -> List[Dict[str, Any]]:
        query_text = f'"{ticker}" OR "{company_name}"' if company_name else ticker
        query = urllib.parse.quote_plus(query_text)
        url = f'https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419'

        collected: List[Dict[str, Any]] = []
        rss = self._fetch_rss(url)
        if rss is None:
            self._errors[ticker] = f'Failed to fetch RSS from {url}'
            return collected

        items = self._parse_rss_items(rss)
        for it in items:
            published = self._parse_published(it.get('published_at'))
            cutoff = as_of.replace(tzinfo=None) if as_of else None
            if cutoff and (published is None or published > cutoff):
                continue
            title = it.get('title') or ''
            sentiment_score = self._score_sentiment(title)
            event_category = self._event_category(title)
            materiality = self._materiality(title)
            record = {
                'timestamp_collected': datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
                'published_at': it.get('published_at'),
                'ticker': ticker,
                'source': it.get('source') or 'google_news',
                'title': title,
                'url': it.get('url'),
                'raw_data': it.get('raw'),
                'source_sha256': hashlib.sha256(
                    str(it.get('raw') or f"{it.get('source')}|{it.get('published_at')}|{title}|{it.get('url')}").encode('utf-8')
                ).hexdigest(),
                'sentiment_score': sentiment_score,
                'sentiment': self._sentiment_label(sentiment_score),
                'event_category': event_category,
                'materiality': materiality,
                'direction': self._sentiment_label(sentiment_score),
                'expected_duration': 'medium' if event_category in {'results', 'regulatory', 'capital_allocation'} else 'short',
                'classification_confidence': 'medium' if materiality == 'high' or sentiment_score != 50.0 else 'low',
                'source_type': 'secondary',
                'point_in_time_eligible': published is not None,
                'event_factual_status': 'SECONDARY_REPORT_UNVERIFIED',
                'interpretation': {
                    'kind': 'DETERMINISTIC_LEXICON_SENTIMENT',
                    'score': sentiment_score,
                    'label': self._sentiment_label(sentiment_score),
                    'limitation': 'A classificação descreve palavras da manchete; não confirma o evento nem seu impacto econômico.',
                },
            }

            duplicate = False
            for existing in self.store.get_all():
                if existing.get('url') and record.get('url') and existing.get('url') == record.get('url'):
                    duplicate = True
                    break
                if (
                    existing.get('ticker') == record.get('ticker')
                    and existing.get('title') == record.get('title')
                    and existing.get('published_at') == record.get('published_at')
                ):
                    duplicate = True
                    break

            if not duplicate:
                self.store.add(record)
                collected.append(record)

        if ticker in self._errors:
            del self._errors[ticker]

        return collected

    @staticmethod
    def _parse_published(value: Any) -> Optional[datetime.datetime]:
        if not value:
            return None
        try:
            return datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            return None

    @staticmethod
    def _event_category(title: str) -> str:
        text = title.lower()
        groups = {
            'results': ('resultado', 'lucro', 'receita', 'ebitda', 'balanço'),
            'capital_allocation': ('dividendo', 'recompra', 'aquisição', 'fusão', 'capex'),
            'regulatory': ('cvm', 'cade', 'anvisa', 'ans', 'regulador', 'investigação', 'bloqueia', 'bloqueou'),
            'operations': ('produção', 'vendas', 'lançamento', 'contrato', 'guidance'),
        }
        return next((name for name, terms in groups.items() if any(term in text for term in terms)), 'general')

    @staticmethod
    def _materiality(title: str) -> str:
        text = title.lower()
        high = ('fato relevante', 'resultado', 'aquisição', 'fusão', 'investigação', 'recuperação judicial', 'guidance', 'bloqueia', 'bloqueou', 'desaba', 'despenca')
        return 'high' if any(term in text for term in high) else 'medium'

    def collect_once(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for ticker in self.tickers:
            try:
                collected = self.collect_ticker(ticker)
                if collected:
                    results.extend(collected)
            except Exception:
                continue

        return results
