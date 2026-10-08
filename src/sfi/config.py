"""Runtime settings read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader: KEY=VALUE lines; never overrides the real environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env(name: str, default: str) -> str:
    # Empty values in .env mean "not set", not "empty string".
    return os.environ.get(name) or default


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Pricing:
    """USD per million tokens, used to estimate the cost of each call."""

    input_usd_per_mtok: float
    output_usd_per_mtok: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_usd_per_mtok + output_tokens * self.output_usd_per_mtok
        ) / 1_000_000


@dataclass(frozen=True)
class AnalysisSettings:
    provider: str = "openai"
    primary_model: str = "gpt-6-luna"
    fallback_model: str | None = "gpt-6.1-sol"
    allowed_models: tuple[str, ...] = ("gpt-6-luna", "gpt-6.1-sol")
    enable_automatic_fallback: bool = False
    prices: dict[str, Pricing] = field(
        default_factory=lambda: {
            "gpt-6-luna": Pricing(0.10, 0.50),
            "gpt-6.1-sol": Pricing(2.00, 10.00),
        }
    )
    total_budget_usd: float = 5.00
    max_cost_per_document_usd: float = 0.25
    max_figures_per_document: int = 25
    max_image_long_side_px: int = 1536
    max_output_tokens: int = 6000
    max_context_chars: int = 6000
    reasoning_effort: str | None = "low"
    image_detail: str = "high"
    language: str = "es"
    concurrency: int = 4
    timeout_s: float = 120.0

    def validate(self) -> None:
        """Fail at startup on configuration that would spend money unpredictably."""
        if self.provider != "openai":
            raise ValueError(f"Unsupported provider {self.provider!r}: the prototype has openai.")
        for model in (self.primary_model, self.fallback_model):
            if model and model not in self.allowed_models:
                raise ValueError(f"Model {model!r} is not in SFI_ALLOWED_MODELS.")
        if self.primary_model not in self.prices:
            raise ValueError(f"No price configured for {self.primary_model!r}.")
        if self.enable_automatic_fallback:
            # ADR 0003: no automatic escalation until a rule has been defined and evaluated.
            raise ValueError(
                "SFI_ENABLE_AUTOMATIC_FALLBACK=true is not supported yet; "
                "use --model to choose the fallback explicitly."
            )
        if self.total_budget_usd <= 0 or self.max_cost_per_document_usd <= 0:
            raise ValueError("Budgets must be positive.")
        if self.max_figures_per_document < 1 or self.max_output_tokens < 256:
            raise ValueError("Per-document and per-figure limits are too small.")

    def pricing(self, model: str) -> Pricing:
        try:
            return self.prices[model]
        except KeyError:
            raise ValueError(f"No price configured for model {model!r}.") from None

    @classmethod
    def from_env(cls) -> AnalysisSettings:
        primary = _env("SFI_PRIMARY_MODEL", "gpt-6-luna")
        fallback = _env("SFI_FALLBACK_MODEL", "") or None
        allowed = tuple(
            m.strip()
            for m in _env("SFI_ALLOWED_MODELS", ",".join(filter(None, [primary, fallback]))).split(
                ","
            )
            if m.strip()
        )
        prices = {
            primary: Pricing(
                float(_env("SFI_PRIMARY_INPUT_USD_PER_MTOK", "0.10")),
                float(_env("SFI_PRIMARY_OUTPUT_USD_PER_MTOK", "0.50")),
            )
        }
        if fallback:
            prices[fallback] = Pricing(
                float(_env("SFI_FALLBACK_INPUT_USD_PER_MTOK", "2.00")),
                float(_env("SFI_FALLBACK_OUTPUT_USD_PER_MTOK", "10.00")),
            )
        effort = _env("SFI_REASONING_EFFORT", "low").strip().lower()
        settings = cls(
            provider=_env("SFI_MULTIMODAL_PROVIDER", "openai"),
            primary_model=primary,
            fallback_model=fallback,
            allowed_models=allowed,
            enable_automatic_fallback=_env_bool("SFI_ENABLE_AUTOMATIC_FALLBACK", False),
            prices=prices,
            total_budget_usd=float(_env("SFI_TOTAL_BUDGET_USD", "5.00")),
            max_cost_per_document_usd=float(_env("SFI_MAX_COST_PER_DOCUMENT_USD", "0.25")),
            max_figures_per_document=int(_env("SFI_MAX_FIGURES_PER_DOCUMENT", "25")),
            max_image_long_side_px=int(_env("SFI_MAX_IMAGE_LONG_SIDE_PX", "1536")),
            max_output_tokens=int(_env("SFI_MAX_OUTPUT_TOKENS_PER_FIGURE", "6000")),
            max_context_chars=int(_env("SFI_MAX_CONTEXT_CHARS", "6000")),
            reasoning_effort=None if effort in {"", "none", "default"} else effort,
            image_detail=_env("SFI_IMAGE_DETAIL", "high"),
            language=_env("SFI_EXPLANATION_LANGUAGE", "es"),
            concurrency=max(1, int(_env("SFI_ANALYSIS_CONCURRENCY", "4"))),
            timeout_s=float(_env("SFI_MODEL_TIMEOUT_S", "120")),
        )
        settings.validate()
        return settings


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    render_dpi: int
    max_pdf_mb: int
    max_pages: int
    analysis: AnalysisSettings = field(default_factory=AnalysisSettings)
    # SFI-48 evaluation corpus: versioned reference and reviews, and the local PDFs/JATS.
    corpus_dir: Path = Path("data/sfi48")
    corpus_raw_dir: Path = Path("data/raw/sfi48")
    # Text inside figures (evidence layer): "auto" uses OCR when the "ocr" extra is
    # installed, "on" requires it, "off" keeps only the PDF text layer.
    figure_ocr: str = "off"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "sfi.sqlite3"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"

    @property
    def report_dir(self) -> Path:
        return self.data_dir / "reports"

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        backend = _env("SFI_DATABASE_BACKEND", "sqlite")
        storage = _env("SFI_STORAGE_BACKEND", "local")
        if backend != "sqlite" or storage != "local":
            raise ValueError(
                f"Unsupported backends {backend!r}/{storage!r}: the prototype supports sqlite/local."
            )
        return cls(
            data_dir=Path(_env("SFI_DATA_DIR", "data/local")),
            render_dpi=int(_env("SFI_RENDER_DPI", "200")),
            max_pdf_mb=int(_env("SFI_MAX_PDF_MB", "100")),
            max_pages=int(_env("SFI_MAX_PAGES", "500")),
            analysis=AnalysisSettings.from_env(),
            corpus_dir=Path(_env("SFI_CORPUS_DIR", "data/sfi48")),
            corpus_raw_dir=Path(_env("SFI_CORPUS_RAW_DIR", "data/raw/sfi48")),
            figure_ocr=_env("SFI_FIGURE_OCR", "auto").strip().lower(),
        )
