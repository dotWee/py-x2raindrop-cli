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
    Settings,
    create_default_config,
    get_default_config_path,
    load_settings,
)
from py_x_bookmarks_to_raindrop_sync.models import LinkMode, SyncResult
from py_x_bookmarks_to_raindrop_sync.raindrop.client import RaindropClient
from py_x_bookmarks_to_raindrop_sync.state import SyncState
from py_x_bookmarks_to_raindrop_sync.sync.service import SyncService
from py_x_bookmarks_to_raindrop_sync.x.auth_pkce import OAuth2Token, PKCEAuthFlow
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


def _get_x_token(settings: Settings) -> OAuth2Token | None:
    """Get X authentication token from settings.

    Checks for direct token first, then falls back to PKCE flow.

    Args:
        settings: Application settings.

    Returns:
        OAuth2Token if authenticated, None otherwise.
    """
    # Check for direct access token first
    if settings.x.has_direct_token():
        direct_token = settings.x.get_direct_token()
        if direct_token:
            logger.debug("Using direct access token")
            return OAuth2Token.from_access_token(direct_token)

    # Fall back to PKCE flow if client_id is configured
    if settings.x.can_use_pkce_flow():
        auth_flow = PKCEAuthFlow(
            client_id=settings.x.client_id,  # type: ignore[arg-type]
            client_secret=settings.x.client_secret,
            redirect_uri=settings.x.redirect_uri,
            scopes=settings.x.scopes,
            token_path=settings.x.token_path,
        )
        return auth_flow.get_token()

    return None


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

        # Get X authentication token
        token = _get_x_token(settings)
        if not token:
            if settings.x.can_use_pkce_flow():
                console.print(
                    "[yellow]Not authenticated with X.[/yellow] "
                    "Run [bold]x2raindrop x login[/bold] first.",
                )
            else:
                console.print(
                    "[red]Error:[/red] No X authentication configured.\n"
                    "Either set X_ACCESS_TOKEN in config/env, or configure "
                    "X_CLIENT_ID for OAuth login.",
                )
            raise typer.Exit(1)

        # Show sync configuration
        if settings.sync.dry_run:
            console.print("[yellow]DRY RUN MODE - No changes will be made[/yellow]\n")

        # Rate limit warning for remove_from_x
        if settings.sync.remove_from_x:
            console.print(
                "[yellow bold]WARNING:[/yellow bold] --remove-from-x is enabled.\n"
                "Each bookmark deletion requires a separate X API request.\n"
                "X API Free Tier only allows 1 request per 15 minutes!\n"
                "Consider using --no-remove-from-x to avoid rate limits.\n"
            )

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
        _display_sync_result(result, x_client.request_count)

        # Cleanup
        x_client.close()
        raindrop_client.close()

    except Exception as e:
        logger.exception("Sync failed")
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


def _display_sync_result(result: SyncResult, x_api_requests: int = 0) -> None:
    """Display sync results in a nice table.

    Args:
        result: Sync result with statistics.
        x_api_requests: Number of X API requests made.
    """
    table = Table(title="Sync Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="green", justify="right")

    table.add_row("Total Bookmarks", str(result.total_bookmarks))
    table.add_row("Newly Synced", str(result.newly_synced))
    table.add_row("Already Synced", str(result.already_synced))
    table.add_row("Failed", str(result.failed))
    table.add_row("Deleted from X", str(result.deleted_from_x))
    table.add_row("X API Requests", str(x_api_requests))

    console.print(table)

    # Rate limit info
    if x_api_requests > 0:
        console.print(
            f"\n[dim]X API requests made: {x_api_requests} "
            "(Free Tier limit: 1 request per 15 min)[/dim]"
        )

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

    NOTE: If you have a direct access token configured (X_ACCESS_TOKEN),
    you don't need to use this command.
    """
    try:
        settings = load_settings(config_path)

        # Check if direct token is already configured
        if settings.x.has_direct_token():
            console.print(
                "[yellow]Direct access token is already configured.[/yellow]\n"
                "You don't need to use the browser login flow.\n"
                "Run [bold]x2raindrop x status[/bold] to check authentication."
            )
            return

        # Check if PKCE flow can be used
        if not settings.x.can_use_pkce_flow():
            console.print(
                "[red]Error:[/red] No X_CLIENT_ID configured.\n"
                "Either set X_CLIENT_ID for OAuth login, or use X_ACCESS_TOKEN directly."
            )
            raise typer.Exit(1)

        auth_flow = PKCEAuthFlow(
            client_id=settings.x.client_id,  # type: ignore[arg-type]
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

        # Check for direct token
        if settings.x.has_direct_token():
            console.print("[green]Authenticated with X (direct token)[/green]")
            table = Table(show_header=False)
            table.add_column("Field", style="cyan")
            table.add_column("Value", style="green")
            table.add_row("Auth method", "Direct access token")
            table.add_row(
                "Token type",
                "access_token" if settings.x.access_token else "bearer_token",
            )
            table.add_row("Token", "***" + (settings.x.get_direct_token() or "")[-8:])
            console.print(table)
            return

        # Check PKCE flow token
        if settings.x.can_use_pkce_flow():
            auth_flow = PKCEAuthFlow(
                client_id=settings.x.client_id,  # type: ignore[arg-type]
                client_secret=settings.x.client_secret,
                redirect_uri=settings.x.redirect_uri,
                scopes=settings.x.scopes,
                token_path=settings.x.token_path,
            )

            token = auth_flow.get_token()

            if token:
                console.print("[green]Authenticated with X (OAuth PKCE)[/green]")
                table = Table(show_header=False)
                table.add_column("Field", style="cyan")
                table.add_column("Value", style="green")
                table.add_row("Auth method", "OAuth 2.0 PKCE")
                table.add_row("Expires at", str(token.expires_at))
                table.add_row("Scopes", token.scope or "(unknown)")
                table.add_row("Token type", token.token_type)
                console.print(table)
                return

        console.print("[yellow]Not authenticated with X[/yellow]")
        console.print(
            "Options:\n"
            "  1. Set X_ACCESS_TOKEN in config for direct authentication\n"
            "  2. Run [bold]x2raindrop x login[/bold] for browser-based OAuth"
        )

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
    """Clear stored X authentication tokens.

    NOTE: This only clears tokens from the PKCE flow. If you're using
    a direct access token (X_ACCESS_TOKEN), remove it from your config.
    """
    try:
        settings = load_settings(config_path)

        # Warn if using direct token
        if settings.x.has_direct_token():
            console.print(
                "[yellow]Note:[/yellow] You have a direct access token configured.\n"
                "This command only clears OAuth PKCE tokens.\n"
                "To remove the direct token, edit your config file."
            )

        # Clear PKCE tokens if configured
        if settings.x.can_use_pkce_flow():
            auth_flow = PKCEAuthFlow(
                client_id=settings.x.client_id,  # type: ignore[arg-type]
                client_secret=settings.x.client_secret,
                redirect_uri=settings.x.redirect_uri,
                scopes=settings.x.scopes,
                token_path=settings.x.token_path,
            )

            auth_flow.logout()
            console.print("[green]Logged out from X (cleared PKCE tokens)[/green]")
        else:
            console.print("[dim]No PKCE tokens to clear.[/dim]")

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
