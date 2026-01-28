"""CLI interface for X Bookmarks to Raindrop.io sync.

This module provides the command-line interface using Typer with
Rich for beautiful terminal output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import structlog
import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn
from rich.table import Table

from py_x_bookmarks_to_raindrop_sync import __version__
from py_x_bookmarks_to_raindrop_sync.config import (
    create_default_config,
    get_default_config_path,
    load_settings,
)
from py_x_bookmarks_to_raindrop_sync.models import LinkMode, SyncResult
from py_x_bookmarks_to_raindrop_sync.raindrop.client import RaindropClient
from py_x_bookmarks_to_raindrop_sync.state import SyncState
from py_x_bookmarks_to_raindrop_sync.sync.service import SyncService
from py_x_bookmarks_to_raindrop_sync.x.auth_pkce import PKCEAuthFlow
from py_x_bookmarks_to_raindrop_sync.x.client import XClient

# Configure structlog for CLI
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Create Typer app
app = typer.Typer(
    name="x2raindrop",
    help="Sync X (Twitter) Bookmarks to Raindrop.io",
    no_args_is_help=True,
)

# Sub-apps for nested commands
x_app = typer.Typer(help="X (Twitter) related commands")
raindrop_app = typer.Typer(help="Raindrop.io related commands")
config_app = typer.Typer(help="Configuration management")

app.add_typer(x_app, name="x")
app.add_typer(raindrop_app, name="raindrop")
app.add_typer(config_app, name="config")

# Rich console for output
console = Console()


def version_callback(value: bool) -> None:
    """Show version and exit."""
    if value:
        console.print(f"x2raindrop version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """X Bookmarks to Raindrop.io sync tool."""
    pass


@app.command()
def sync(
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to config file",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
    collection_id: Annotated[
        int | None,
        typer.Option(
            "--collection",
            help="Target Raindrop collection ID",
        ),
    ] = None,
    tags: Annotated[
        str | None,
        typer.Option(
            "--tags",
            "-t",
            help="Comma-separated tags to apply",
        ),
    ] = None,
    remove_from_x: Annotated[
        bool,
        typer.Option(
            "--remove-from-x/--no-remove-from-x",
            help="Remove bookmarks from X after syncing",
        ),
    ] = False,
    link_mode: Annotated[
        LinkMode | None,
        typer.Option(
            "--link-mode",
            "-l",
            help="Link resolution mode",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Don't make any changes, just show what would happen",
        ),
    ] = False,
) -> None:
    """Sync X bookmarks to Raindrop.io.

    Fetches your X bookmarks and creates corresponding Raindrop.io
    bookmarks in the configured collection.
    """
    try:
        # Load settings
        settings = load_settings(config_path)

        # Override settings from CLI flags
        if collection_id is not None:
            settings.sync.collection_id = collection_id
        if tags is not None:
            settings.sync.tags = [t.strip() for t in tags.split(",") if t.strip()]
        if remove_from_x:
            settings.sync.remove_from_x = True
        if link_mode is not None:
            settings.sync.link_mode = link_mode
        if dry_run:
            settings.sync.dry_run = True

        # Validate collection ID
        if settings.sync.collection_id is None:
            console.print(
                "[red]Error:[/red] No collection ID specified. "
                "Use --collection or set SYNC_COLLECTION_ID.",
                style="bold",
            )
            raise typer.Exit(1)

        # Initialize X auth
        auth_flow = PKCEAuthFlow(
            client_id=settings.x.client_id,
            client_secret=settings.x.client_secret,
            redirect_uri=settings.x.redirect_uri,
            scopes=settings.x.scopes,
            token_path=settings.x.token_path,
        )

        # Check X authentication
        token = auth_flow.get_token()
        if not token:
            console.print(
                "[yellow]Not authenticated with X.[/yellow] "
                "Run [bold]x2raindrop x login[/bold] first.",
            )
            raise typer.Exit(1)

        # Show sync configuration
        if settings.sync.dry_run:
            console.print("[yellow]DRY RUN MODE - No changes will be made[/yellow]\n")

        table = Table(title="Sync Configuration", show_header=False)
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Collection ID", str(settings.sync.collection_id))
        table.add_row("Tags", ", ".join(settings.sync.tags) or "(none)")
        table.add_row("Link Mode", settings.sync.link_mode.value)
        table.add_row("Remove from X", "Yes" if settings.sync.remove_from_x else "No")
        console.print(table)
        console.print()

        # Initialize clients
        x_client = XClient(token)
        raindrop_client = RaindropClient(settings.raindrop.token)
        state = SyncState(settings.sync.state_path)

        # Create sync service
        service = SyncService(
            x_client=x_client,
            raindrop_client=raindrop_client,
            state=state,
            settings=settings.sync,
        )

        # Run sync with progress
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task: TaskID = progress.add_task("Syncing bookmarks...", total=None)

            def update_progress(current: int, total: int, message: str) -> None:
                progress.update(task, total=total, completed=current, description=message)

            result = service.sync(progress_callback=update_progress)

        # Show results
        _display_sync_result(result)

        # Cleanup
        x_client.close()
        raindrop_client.close()

    except Exception as e:
        logger.exception("Sync failed")
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


def _display_sync_result(result: SyncResult) -> None:
    """Display sync results in a nice table."""
    table = Table(title="Sync Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="green", justify="right")

    table.add_row("Total Bookmarks", str(result.total_bookmarks))
    table.add_row("Newly Synced", str(result.newly_synced))
    table.add_row("Already Synced", str(result.already_synced))
    table.add_row("Failed", str(result.failed))
    table.add_row("Deleted from X", str(result.deleted_from_x))

    console.print(table)

    if result.errors:
        console.print("\n[yellow]Errors:[/yellow]")
        for error in result.errors:
            console.print(f"  - {error}")


# X subcommands
@x_app.command("login")
def x_login(
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to config file",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
) -> None:
    """Authenticate with X using OAuth 2.0 PKCE flow.

    Opens a browser for you to authorize the app. The tokens are
    stored locally for future use.
    """
    try:
        settings = load_settings(config_path)

        auth_flow = PKCEAuthFlow(
            client_id=settings.x.client_id,
            client_secret=settings.x.client_secret,
            redirect_uri=settings.x.redirect_uri,
            scopes=settings.x.scopes,
            token_path=settings.x.token_path,
        )

        console.print("Starting X OAuth 2.0 login flow...")
        console.print("A browser window will open for authorization.\n")

        token = auth_flow.login()

        console.print("[green]Successfully authenticated with X![/green]")
        console.print(f"Token expires at: {token.expires_at}")
        console.print(f"Scopes: {token.scope}")

    except TimeoutError:
        console.print("[red]Error:[/red] Authorization timed out.")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@x_app.command("status")
def x_status(
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to config file",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
) -> None:
    """Check X authentication status."""
    try:
        settings = load_settings(config_path)

        auth_flow = PKCEAuthFlow(
            client_id=settings.x.client_id,
            client_secret=settings.x.client_secret,
            redirect_uri=settings.x.redirect_uri,
            scopes=settings.x.scopes,
            token_path=settings.x.token_path,
        )

        token = auth_flow.get_token()

        if token:
            console.print("[green]Authenticated with X[/green]")
            table = Table(show_header=False)
            table.add_column("Field", style="cyan")
            table.add_column("Value", style="green")
            table.add_row("Expires at", str(token.expires_at))
            table.add_row("Scopes", token.scope)
            table.add_row("Token type", token.token_type)
            console.print(table)
        else:
            console.print("[yellow]Not authenticated with X[/yellow]")
            console.print("Run [bold]x2raindrop x login[/bold] to authenticate.")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@x_app.command("logout")
def x_logout(
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to config file",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
) -> None:
    """Clear stored X authentication tokens."""
    try:
        settings = load_settings(config_path)

        auth_flow = PKCEAuthFlow(
            client_id=settings.x.client_id,
            client_secret=settings.x.client_secret,
            redirect_uri=settings.x.redirect_uri,
            scopes=settings.x.scopes,
            token_path=settings.x.token_path,
        )

        auth_flow.logout()
        console.print("[green]Logged out from X[/green]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


# Raindrop subcommands
@raindrop_app.command("collections")
def raindrop_collections(
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to config file",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
) -> None:
    """List available Raindrop.io collections."""
    try:
        settings = load_settings(config_path)

        client = RaindropClient(settings.raindrop.token)
        collections = client.list_collections()
        client.close()

        table = Table(title="Raindrop.io Collections")
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Title", style="green")
        table.add_column("Items", justify="right")
        table.add_column("Parent ID", justify="right")

        for c in sorted(collections, key=lambda x: x.title.lower()):
            table.add_row(
                str(c.id),
                c.title,
                str(c.count),
                str(c.parent_id) if c.parent_id else "-",
            )

        console.print(table)
        console.print(f"\nTotal: {len(collections)} collections")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


# Config subcommands
@config_app.command("init")
def config_init(
    path: Annotated[
        Path | None,
        typer.Option(
            "--path",
            "-p",
            help="Path for config file",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Overwrite existing config file",
        ),
    ] = False,
) -> None:
    """Create a default configuration file."""
    try:
        if path is None:
            path = get_default_config_path()

        if path.exists() and not force:
            console.print(f"[yellow]Config file already exists:[/yellow] {path}")
            console.print("Use --force to overwrite.")
            raise typer.Exit(1)

        created_path = create_default_config(path)
        console.print(f"[green]Created config file:[/green] {created_path}")
        console.print("\nEdit this file to add your API credentials.")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@config_app.command("show")
def config_show(
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to config file",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
) -> None:
    """Show current configuration (with secrets masked)."""
    try:
        settings = load_settings(config_path)

        table = Table(title="Current Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")

        # X settings
        table.add_row(
            "X Client ID", settings.x.client_id[:8] + "..." if settings.x.client_id else "(not set)"
        )
        table.add_row("X Client Secret", "***" if settings.x.client_secret else "(not set)")
        table.add_row("X Redirect URI", settings.x.redirect_uri)
        table.add_row("X Token Path", str(settings.x.token_path))

        # Raindrop settings
        table.add_row("Raindrop Token", "***" if settings.raindrop.token else "(not set)")

        # Sync settings
        table.add_row(
            "Collection ID",
            str(settings.sync.collection_id) if settings.sync.collection_id else "(not set)",
        )
        table.add_row("Tags", ", ".join(settings.sync.tags) or "(none)")
        table.add_row("Remove from X", str(settings.sync.remove_from_x))
        table.add_row("Link Mode", settings.sync.link_mode.value)
        table.add_row("Both Behavior", settings.sync.both_behavior.value)
        table.add_row("State Path", str(settings.sync.state_path))

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@config_app.command("path")
def config_path_cmd() -> None:
    """Show the default config file path."""
    console.print(f"Default config path: {get_default_config_path()}")


if __name__ == "__main__":
    app()
