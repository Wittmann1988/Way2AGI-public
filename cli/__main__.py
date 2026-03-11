"""Way2AGI CLI Entry-Point."""
import click


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """Way2AGI — Dein persoenlicher KI-Agent."""
    if ctx.invoked_subcommand is None:
        from cli.app import Way2AGIApp
        app = Way2AGIApp()
        app.run()


@main.command()
def chat():
    """Direkt in den Chat-Modus."""
    from cli.app import Way2AGIApp
    app = Way2AGIApp(start_screen="chat")
    app.run()


@main.command()
def models():
    """Model-Auswahl oeffnen."""
    from cli.app import Way2AGIApp
    app = Way2AGIApp(start_screen="models")
    app.run()


@main.command()
def settings():
    """Einstellungen oeffnen."""
    from cli.app import Way2AGIApp
    app = Way2AGIApp(start_screen="settings")
    app.run()


@main.command()
def memory():
    """Memory Browser oeffnen."""
    from cli.app import Way2AGIApp
    app = Way2AGIApp(start_screen="memory")
    app.run()


@main.command()
def orchestrator():
    """Orchestrator-Ansicht oeffnen."""
    from cli.app import Way2AGIApp
    app = Way2AGIApp(start_screen="orchestrator")
    app.run()


@main.command()
def sysmon():
    """System Monitor oeffnen."""
    from cli.app import Way2AGIApp
    app = Way2AGIApp(start_screen="sysmon")
    app.run()


@main.command()
def mcp():
    """MCP Server Manager oeffnen."""
    from cli.app import Way2AGIApp
    app = Way2AGIApp(start_screen="mcp")
    app.run()


@main.command()
def doctor():
    """Systemdiagnose ausfuehren."""
    from cli.app import Way2AGIApp
    app = Way2AGIApp(start_screen="diagnostics")
    app.run()


if __name__ == "__main__":
    main()
