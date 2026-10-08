"""Command line interface.

sfi process FILE.pdf [FILE.pdf ...] [--force]   extract figures and explain them
sfi analyze [DOC_ID_PREFIX] [--force]            explain figures already extracted
sfi list                                         list processed documents
sfi show DOC_ID_PREFIX                           print figures of a document
sfi report [DOC_ID_PREFIX]                       write the HTML gallery
sfi costs                                        spending against the budget
sfi serve [--port 8000] [--open]                 local web application
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sfi.analysis.analyzer import (
    AnalysisUnavailable,
    DocumentAnalysis,
    FigureAnalyzer,
    FigureOutcome,
    build_analyzer,
)
from sfi.config import Settings
from sfi.ingest import InvalidDocumentError
from sfi.pipeline import FigurePipeline
from sfi.report import write_document_report, write_index


def _short(document_id: str) -> str:
    return document_id.split(":")[-1][:12]


class Analysis:
    """Builds the analyzer on first use, so commands that do not call the model never need a key."""

    def __init__(self, pipeline: FigurePipeline, args: argparse.Namespace):
        self.pipeline = pipeline
        self.args = args
        self._analyzer: FigureAnalyzer | None = None
        self.unavailable: str | None = None

    def get(self) -> FigureAnalyzer | None:
        if self._analyzer is None and self.unavailable is None:
            try:
                self._analyzer = build_analyzer(
                    self.pipeline.settings.analysis,
                    self.pipeline.repository,
                    self.pipeline.blobs,
                    model_id=getattr(self.args, "model", None),
                )
            except AnalysisUnavailable as exc:
                self.unavailable = str(exc)
        return self._analyzer

    def run(self, document, figures, force: bool) -> DocumentAnalysis | None:
        analyzer = self.get()
        if analyzer is None:
            return None
        result = analyzer.analyze(
            document,
            figures,
            force=force,
            max_figures=getattr(self.args, "max_figures", None),
            progress=_print_outcome,
        )
        explained = sum(1 for o in result.outcomes if o.status.value == "ok")
        print(
            f"        {explained}/{len(result.outcomes)} explained, "
            f"{result.spent_usd:.4f} USD this run, {analyzer.total_spent():.4f} USD in total"
        )
        if result.stopped:
            print(f"        ! analysis stopped: {result.stopped}", file=sys.stderr)
        return result


def _print_outcome(outcome: FigureOutcome) -> None:
    label = outcome.figure.label or "unlabelled"
    if outcome.source == "skipped":
        print(f"        {label:<24} skipped     {outcome.message}")
        return
    analysis = outcome.analysis
    detail = ""
    if analysis and analysis.run:
        timing = f"{analysis.run.latency_ms / 1000:.1f} s" if outcome.source == "model" else "cache"
        detail = f"{analysis.cost_usd:.4f} USD  {timing}"
    errors = [i.code for i in (analysis.issues if analysis else []) if i.severity == "error"]
    if errors:
        detail += f"  [{', '.join(sorted(set(errors)))}]"
    if outcome.message:
        detail += f"  {outcome.message}"
    print(f"        {label:<24} {outcome.status.value:<11} {detail}")


def cmd_process(pipeline: FigurePipeline, args: argparse.Namespace) -> int:
    failures = 0
    analysis = None if args.extract_only else Analysis(pipeline, args)
    for path in args.files:
        try:
            result = pipeline.process(Path(path), force=args.force)
        except InvalidDocumentError as exc:
            print(f"ERROR   {path}: [{exc.code}] {exc}", file=sys.stderr)
            failures += 1
            continue
        except FileNotFoundError:
            print(f"ERROR   {path}: file not found", file=sys.stderr)
            failures += 1
            continue
        ok = sum(1 for f in result.figures if f.status == "ok")
        incomplete = len(result.figures) - ok
        source = "cache" if result.cached else f"{result.run.duration_ms} ms"
        print(
            f"ok      {path}: {ok} figures, {incomplete} incomplete, "
            f"{len(result.run.warnings)} warnings ({source}) id={_short(result.document.id)}"
        )
        if analysis is None:
            continue
        outcome = analysis.run(result.document, result.figures, force=args.reanalyze)
        if analysis.unavailable:
            print(
                f"        figures not explained: {analysis.unavailable} "
                "(use --extract-only to skip analysis)",
                file=sys.stderr,
            )
            analysis = None
        elif outcome and outcome.fatal:
            print("        stopping: the model cannot be used.", file=sys.stderr)
            return 1
    return 1 if failures else 0


def _documents(pipeline: FigurePipeline, prefix: str):
    for document in pipeline.repository.find_documents(prefix):
        run = pipeline.repository.latest_completed_run(document.id)
        if run:
            yield document, run, pipeline.repository.list_figures(run.id)


def cmd_analyze(pipeline: FigurePipeline, args: argparse.Namespace) -> int:
    entries = list(_documents(pipeline, args.document or ""))
    if not entries:
        print("Nothing to analyze: process a PDF first.", file=sys.stderr)
        return 1
    analysis = Analysis(pipeline, args)
    if analysis.get() is None:
        print(f"ERROR   {analysis.unavailable}", file=sys.stderr)
        return 1
    for document, _run, figures in entries:
        print(f"analyze {document.filename} id={_short(document.id)}")
        outcome = analysis.run(document, figures, force=args.force)
        if outcome and outcome.fatal:
            return 1
    return 0


def cmd_list(pipeline: FigurePipeline, args: argparse.Namespace) -> int:
    for document, _run, figures in _documents(pipeline, ""):
        explained = sum(
            1
            for f in figures
            if (a := pipeline.repository.latest_analysis(f.id)) and a.status.value == "ok"
        )
        print(
            f"{_short(document.id)}  {document.page_count:>3} pages  {len(figures):>3} figures  "
            f"{explained:>3} explained  {document.filename}"
        )
    return 0


def cmd_show(pipeline: FigurePipeline, args: argparse.Namespace) -> int:
    found = list(_documents(pipeline, args.document))
    if not found:
        print(f"No processed document matches {args.document!r}", file=sys.stderr)
        return 1
    for document, run, figures in found:
        print(f"{document.filename} ({_short(document.id)}), run {run.id[:12]}")
        for figure in figures:
            caption = figure.caption.text[:70] if figure.caption else ""
            analysis = pipeline.repository.latest_analysis(figure.id)
            explained = analysis.status.value if analysis else "-"
            print(
                f"  p{figure.page_index + 1:<3} {figure.label or '-':<26} {figure.status:<12} "
                f"{figure.confidence:.2f}  {explained:<10} {caption}"
            )
            if analysis and analysis.explanation:
                print(f"       {analysis.explanation.summary}")
        for warning in run.warnings:
            if warning.code.value != "scanned_page":
                print(f"  ! {warning.message}")
    return 0


def cmd_report(pipeline: FigurePipeline, args: argparse.Namespace) -> int:
    entries = list(_documents(pipeline, args.document or ""))
    if not entries:
        print("Nothing to report: process a PDF first.", file=sys.stderr)
        return 1
    out = pipeline.settings.report_dir
    for document, run, figures in entries:
        path = write_document_report(
            document, run, figures, pipeline.repository, pipeline.blobs, out
        )
        print(f"report  {path}")
    all_entries = list(_documents(pipeline, ""))
    print(f"index   {write_index(all_entries, out, pipeline.repository)}")
    return 0


def cmd_costs(pipeline: FigurePipeline, args: argparse.Namespace) -> int:
    rows = pipeline.repository.analysis_spend()
    names = {d.id: d.filename for d in pipeline.repository.find_documents()}
    total = sum(row[3] for row in rows)
    budget = pipeline.settings.analysis.total_budget_usd
    for document_id, model, calls, usd in rows:
        print(
            f"{names.get(document_id, _short(document_id)):<28} {model:<14} {calls:>4} calls  {usd:.4f} USD"
        )
    print(f"total {total:.4f} USD of {budget:.2f} USD budget ({budget - total:.4f} USD left)")
    print(
        "Estimated from token counts and configured prices; cached input is charged at full price."
    )
    return 0


def cmd_serve(settings: Settings, args: argparse.Namespace) -> int:
    import threading
    import webbrowser

    import uvicorn

    from sfi.web.app import create_app

    url = f"http://{args.host}:{args.port}/"
    print(f"Scientific Figure Intelligence en {url}  (Ctrl+C para salir)")
    if args.open:
        threading.Timer(1.5, webbrowser.open, (url,)).start()
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # Windows consoles may not encode every character in captions and explanations.
        stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="sfi", description="Scientific Figure Intelligence")
    sub = parser.add_subparsers(dest="command", required=True)

    def analysis_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--model", help="model id (must be in SFI_ALLOWED_MODELS)")
        p.add_argument("--max-figures", type=int, help="analyze at most N figures per document")

    p_process = sub.add_parser("process", help="extract figures from PDFs and explain them")
    p_process.add_argument("files", nargs="+")
    p_process.add_argument("--force", action="store_true", help="ignore cached extraction")
    p_process.add_argument("--reanalyze", action="store_true", help="ignore cached explanations")
    p_process.add_argument("--extract-only", action="store_true", help="do not call the model")
    p_process.add_argument("--report", action="store_true", help="also write the HTML gallery")
    analysis_options(p_process)
    p_analyze = sub.add_parser("analyze", help="explain figures of processed documents")
    p_analyze.add_argument("document", nargs="?", help="document id prefix (default: all)")
    p_analyze.add_argument("--force", action="store_true", help="ignore cached explanations")
    p_analyze.add_argument("--report", action="store_true", help="also write the HTML gallery")
    analysis_options(p_analyze)
    sub.add_parser("list", help="list processed documents")
    p_show = sub.add_parser("show", help="print the figures of a document")
    p_show.add_argument("document", help="document id prefix")
    p_report = sub.add_parser("report", help="write the HTML gallery")
    p_report.add_argument("document", nargs="?", help="document id prefix (default: all)")
    sub.add_parser("costs", help="show model spending against the budget")
    p_serve = sub.add_parser("serve", help="run the local web application")
    p_serve.add_argument("--host", default="127.0.0.1", help="default: localhost only")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--open", action="store_true", help="open the browser")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.command == "serve":
        return cmd_serve(settings, args)
    pipeline = FigurePipeline.from_settings(settings)
    if args.command in {"process", "analyze"}:
        status = (cmd_process if args.command == "process" else cmd_analyze)(pipeline, args)
        if args.report:
            args.document = None
            cmd_report(pipeline, args)
        return status
    commands = {"list": cmd_list, "show": cmd_show, "report": cmd_report, "costs": cmd_costs}
    return commands[args.command](pipeline, args)


if __name__ == "__main__":
    sys.exit(main())
