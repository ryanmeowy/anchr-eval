"""CLI entry points. Remote mutations are explicit commands."""
from pathlib import Path
import json
import typer

from .client import AnchrClient, ApiError, Config
from .data import dataset, now, write_json

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


def remote(root, function):
    try:
        with AnchrClient(Config.load(root)) as client:
            return function(root,client,typer.echo)
    except (ApiError, ValueError) as exc:
        typer.echo(str(exc),err=True)
        raise typer.Exit(1)


@app.command()
def ingest(root: Path = Path('.')):
    """Create the managed KB, upload PDFs and submit one idempotent ingestion task."""
    from .ingestion import prepare
    remote(root,prepare)


@app.command()
def status(root: Path = Path('.')):
    """Refresh ingestion and document readiness once (no implicit retry)."""
    from .ingestion import refresh
    remote(root,refresh)


@app.command()
def retry_failed(root: Path = Path('.')):
    """Explicitly retry failed ingestion items after fixing the server-side cause."""
    from .ingestion import retry_failed as retry
    remote(root,retry)


@app.command()
def bind(root: Path = Path('.')):
    """Bind evidence to observed search segments; partial matches remain unverified."""
    from .binding import bind as bind_evidence
    remote(root,bind_evidence)


@app.command()
def review_bindings(review: Path = Path('runs/setup/binding-review.json'), root: Path = Path('.')):
    """Apply explicit evidence reviews to a matching captured snapshot, without API calls."""
    from .review import review_bindings as apply
    try:
        apply(root,review,typer.echo)
    except (ApiError,ValueError,KeyError) as exc:
        typer.echo(str(exc),err=True)
        raise typer.Exit(1)


@app.command()
def smoke(case_id: str = 'ANCHR-010-001', root: Path = Path('.')):
    """Run one scoped search + traditional answer and preserve raw results (no auto-score)."""
    from .runner import smoke as run_smoke
    remote(root, lambda root,client,emit:run_smoke(root,client,case_id,emit))


@app.command()
def batch(name: str = 'baseline-v1', reuse_run: str = '', root: Path = Path('.')):
    """Run all ten cases sequentially; persist progress and never blindly repeat a case."""
    from .batch import run_batch
    remote(root,lambda root,client,emit:run_batch(root,client,name,reuse_run=reuse_run or None,emit=emit))


@app.command()
def score(name: str = 'baseline-v1', root: Path = Path('.')):
    """Aggregate explicitly reviewed labels offline; never ask a model to grade silently."""
    from .scoring import score_batch
    try:
        score_batch(root,name,root/'runs'/name/'review.json',typer.echo)
    except (ApiError,ValueError,KeyError) as exc:
        typer.echo(str(exc),err=True)
        raise typer.Exit(1)


@app.command()
def validate(root: Path = Path('.')):
    """Validate the frozen dataset and upload document hashes."""
    corpus, cases = dataset(root)
    typer.echo(f"Valid: {len(cases)} cases, {len(corpus['documents'])} documents.")


@app.command()
def doctor(root: Path = Path('.')):
    """Verify token and conversation capabilities without changing server data."""
    config = Config.load(root)
    try:
        with AnchrClient(config) as client:
            result = {'checked_at': now(), 'base_url': config.base_url,
                      'auth': client.get('/api/v1/auth/validate-token'),
                      'capabilities': client.get('/api/v1/conversations/capabilities')}
        write_json(root / 'runs/setup/doctor.json', result)
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    except ApiError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
