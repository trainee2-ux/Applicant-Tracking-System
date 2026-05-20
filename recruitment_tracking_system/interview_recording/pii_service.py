import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Singletons for cached engines
_ANALYZER_ENGINE = None
_ANONYMIZER_ENGINE = None


def _optional_presidio():
    try:
        from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, EntityRecognizer, RecognizerResult
        from presidio_anonymizer import AnonymizerEngine

        return AnalyzerEngine, RecognizerRegistry, EntityRecognizer, RecognizerResult, AnonymizerEngine
    except Exception as exc:
        logger.warning(
            "Presidio dependencies are not available (%s). "
            "PII redaction will be skipped. Fix by installing `presidio-analyzer` "
            "and `presidio-anonymizer` in the active environment.",
            exc,
        )
        return None


def _get_anonymizer():
    deps = _optional_presidio()
    if deps is None:
        return None
    *_, AnonymizerEngine = deps

    global _ANONYMIZER_ENGINE
    if _ANONYMIZER_ENGINE is None:
        _ANONYMIZER_ENGINE = AnonymizerEngine()
    return _ANONYMIZER_ENGINE

def _ensure_hf_imports():
    from pathlib import Path
    import sys
    import os
    import re

    # Prefer the bundled runtime dependencies if present to avoid venv mismatch.
    runtime_site_packages = Path(__file__).resolve().parents[1] / "runtime" / "site-packages"
    runtime_site_packages_str = str(runtime_site_packages)
    if runtime_site_packages.exists() and runtime_site_packages_str not in sys.path:
        sys.path.insert(0, runtime_site_packages_str)
        prefixes = ("huggingface_hub", "transformers", "httpx", "httpcore", "certifi")
        for name in list(sys.modules.keys()):
            if name == "certifi" or name.startswith(prefixes):
                sys.modules.pop(name, None)

    try:
        import certifi  # noqa: F401

        # Clear the known-bad localhost:9 proxy if present, otherwise HF downloads fail.
        bad_proxy_re = re.compile(r"(?i)(?:^|//)(?:localhost|127\.0\.0\.1):9\b")
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            value = (os.environ.get(key) or "").strip()
            if value and bad_proxy_re.search(value):
                os.environ.pop(key, None)

        # Ensure cache dir is writable.
        cache_root = (os.environ.get("ATS_HF_HOME") or "").strip()
        if not cache_root:
            cache_root = str((Path(__file__).resolve().parents[1] / "hf_cache").resolve())
        try:
            os.makedirs(cache_root, exist_ok=True)
            os.environ["HF_HOME"] = cache_root
            os.environ["TRANSFORMERS_CACHE"] = os.path.join(cache_root, "transformers")
        except Exception:
            pass

        return
    except Exception as exc:
        raise RuntimeError(
            "Hugging Face dependencies could not be imported (missing `certifi`). "
            "Install project dependencies in the active environment, e.g. "
            "`python -m pip install -r requirements.txt`."
        ) from exc


def _transformers_recognizer_base():
    deps = _optional_presidio()
    if deps is None:
        return None

    _AnalyzerEngine, _RecognizerRegistry, EntityRecognizer, _RecognizerResult, _AnonymizerEngine = deps
    return EntityRecognizer


_EntityRecognizer = _transformers_recognizer_base()


class TransformersRecognizer(_EntityRecognizer if _EntityRecognizer is not None else object):
    """
    Custom Presidio EntityRecognizer using a Hugging Face token-classification pipeline.
    Provides deep neural NER context recognition to prevent vulnerabilities in downstream ML models.
    """
    def __init__(self, model_name: str = "dslim/bert-base-NER", supported_entities: Optional[List[str]] = None):
        deps = _optional_presidio()
        if deps is None:
            raise RuntimeError("Presidio is required to use TransformersRecognizer.")

        _AnalyzerEngine, _RecognizerRegistry, EntityRecognizer, _RecognizerResult, _AnonymizerEngine = deps

        if not supported_entities:
            # Map standard Hugging Face NER entities to Presidio entities
            supported_entities = ["PERSON", "LOCATION", "ORGANIZATION"]
        
        super().__init__(supported_entities=supported_entities, name="Transformers NER Recognizer")
        self.model_name = model_name
        self.pipeline = None

    def load(self) -> None:
        """Loads Hugging Face pipeline lazily to save resources."""
        if self.pipeline is None:
            _ensure_hf_imports()
            from transformers import pipeline
            self.pipeline = pipeline("token-classification", model=self.model_name, aggregation_strategy="simple")

    def analyze(self, text: str, entities: List[str], nlp_artifacts=None):
        """Runs Hugging Face NER pipeline and converts findings to Presidio format."""
        if not text:
            return []

        self.load()
        if not self.pipeline:
            return []

        results = self.pipeline(text)
        recognizer_results = []

        deps = _optional_presidio()
        if deps is None:
            return []
        _AnalyzerEngine, _RecognizerRegistry, _EntityRecognizer, RecognizerResult, _AnonymizerEngine = deps

        # Map typical Hugging Face NER outputs to Presidio types
        label_map = {
            "PER": "PERSON",
            "LOC": "LOCATION",
            "ORG": "ORGANIZATION",
            "I-PER": "PERSON",
            "B-PER": "PERSON",
            "I-LOC": "LOCATION",
            "B-LOC": "LOCATION",
            "I-ORG": "ORGANIZATION",
            "B-ORG": "ORGANIZATION",
        }

        for res in results:
            entity_label = res.get("entity_group") or res.get("entity")
            mapped_entity = label_map.get(entity_label)
            
            if mapped_entity and mapped_entity in entities:
                recognizer_results.append(
                    RecognizerResult(
                        entity_type=mapped_entity,
                        start=res["start"],
                        end=res["end"],
                        score=float(res["score"])
                    )
                )

        return recognizer_results


def _create_spacy_nlp_engine():
    """Creates a spaCy NLP engine using the pre-installed en_core_web_sm model."""
    deps = _optional_presidio()
    if deps is None:
        raise RuntimeError("Presidio is required to create the NLP engine.")

    from presidio_analyzer.nlp_engine import NlpEngineProvider

    configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
    }
    provider = NlpEngineProvider(nlp_configuration=configuration)
    return provider.create_engine()

def get_analyzer(use_hf: bool = False, hf_model: str = "dslim/bert-base-NER"):
    """
    Retrieves or initializes the Presidio AnalyzerEngine.
    If use_hf is True, loads the custom Hugging Face model and registers it.
    Otherwise, uses the lightweight pre-installed spaCy engine.
    """
    deps = _optional_presidio()
    if deps is None:
        return None

    AnalyzerEngine, RecognizerRegistry, _EntityRecognizer, _RecognizerResult, _AnonymizerEngine = deps

    global _ANALYZER_ENGINE
    if not use_hf:
        if _ANALYZER_ENGINE is None:
            try:
                nlp_engine = _create_spacy_nlp_engine()
                _ANALYZER_ENGINE = AnalyzerEngine(nlp_engine=nlp_engine)
            except Exception as e:
                logger.warning(f"Failed to load configured en_core_web_sm engine: {e}. Attempting default initialization.")
                _ANALYZER_ENGINE = AnalyzerEngine()
        return _ANALYZER_ENGINE

    try:
        registry = RecognizerRegistry()
        registry.load_predefined_recognizers()
        
        hf_recognizer = TransformersRecognizer(model_name=hf_model)
        hf_recognizer.load()
        registry.add_recognizer(hf_recognizer)
        
        nlp_engine = _create_spacy_nlp_engine()
        return AnalyzerEngine(nlp_engine=nlp_engine, registry=registry)
    except Exception as exc:
        logger.warning(f"Unable to load Hugging Face model '{hf_model}': {exc}. Falling back to default Presidio analyzer.")
        if _ANALYZER_ENGINE is None:
            try:
                nlp_engine = _create_spacy_nlp_engine()
                _ANALYZER_ENGINE = AnalyzerEngine(nlp_engine=nlp_engine)
            except Exception as e:
                _ANALYZER_ENGINE = AnalyzerEngine()
        return _ANALYZER_ENGINE


def redact_pii(text: str, use_hf: bool = False, hf_model: str = "dslim/bert-base-NER") -> tuple[str, bool]:
    """
    Scans text for PII entities (PERSON, EMAIL, PHONE, LOCATION, SSN) and masks them.
    
    Returns:
        tuple[str, bool]: (redacted_text, was_pii_found)
    """
    if not text or not text.strip():
        return text, False

    try:
        analyzer = get_analyzer(use_hf=use_hf, hf_model=hf_model)
        if analyzer is None:
            return text, False

        anonymizer = _get_anonymizer()
        if anonymizer is None:
            return text, False

        entities_to_detect = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION", "US_SSN"]
        results = analyzer.analyze(text=text, entities=entities_to_detect, language="en")
        
        if not results:
            return text, False

        anonymized_result = anonymizer.anonymize(text=text, analyzer_results=results)
        redacted_text = anonymized_result.text
        
        was_pii_found = redacted_text != text
        return redacted_text, was_pii_found

    except Exception as exc:
        logger.error(f"Error executing Presidio PII redaction: {exc}")
        return text, False
