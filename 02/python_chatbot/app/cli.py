"""Interactive command-line interface of the Python Tutor.

Run with:  uv run python -m app.cli

The CLI only handles input/output (rich rendering, commands, errors); every
question is delegated to `ChatService`.
"""

import logging
import uuid
from collections.abc import Callable

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from app.core.config import get_settings
from app.core.exceptions import ChatbotError, MissingAPIKeyError
from app.core.logging import configure_logging
from app.core.tracing import configure_tracing
from app.services.chat_service import ChatService, create_chat_service

logger = logging.getLogger(__name__)

PROMPT = "[bold green]You[/bold green] [dim]>[/dim] "
ASSISTANT_LABEL = "[bold cyan]Python Tutor[/bold cyan]"

SUGGESTED_QUESTIONS: tuple[str, ...] = (
    "How do I create a list in Python?",
    "Como criar uma lista em Python?",
    "What is the difference between a list and a tuple?",
    "What are decorators?",
)

COMMANDS: dict[str, str] = {
    "/help": "Show this list of commands",
    "/clear": "Clear the conversation history (start a new topic)",
    "/exit": "Quit the chat (Ctrl+C also works)",
}

EXIT_COMMANDS = frozenset({"/exit", "/quit"})


class ChatCLI:
    """Interactive chat loop.

    Args:
        service: Service that answers the questions.
        console: Rich console used for all output (injectable for tests).
        session_id: Conversation id; a new UUID by default.
    """

    def __init__(
        self,
        service: ChatService,
        console: Console | None = None,
        session_id: str | None = None,
    ) -> None:
        """Create the CLI bound to a chat service."""
        self._service = service
        self._console = console or Console()
        self._session_id = session_id or f"cli-{uuid.uuid4()}"

    @property
    def session_id(self) -> str:
        """Identifier of the current conversation."""
        return self._session_id

    # --- Output -------------------------------------------------------------------

    def show_welcome(self) -> None:
        """Print the welcome panel with suggested questions."""
        suggestions = "\n".join(f"  • {question}" for question in SUGGESTED_QUESTIONS)
        self._console.print(
            Panel(
                "Hi! I'm your [bold]Python Tutor[/bold]. Ask me anything about Python "
                "programming, in any language.\n\n"
                f"[bold]Try asking:[/bold]\n{suggestions}\n\n"
                "Type [bold]/help[/bold] to see the commands.",
                title="🐍 Python Tutor",
                border_style="cyan",
            )
        )

    def show_help(self) -> None:
        """Print the table of special commands."""
        table = Table(title="Commands", show_header=True, header_style="bold cyan")
        table.add_column("Command")
        table.add_column("Description")
        for command, description in COMMANDS.items():
            table.add_row(command, description)
        self._console.print(table)

    # --- Input handling -----------------------------------------------------------

    def handle_command(self, command: str) -> bool:
        """Execute a special command.

        Args:
            command: Text starting with "/".

        Returns:
            False when the chat must end, True to keep running.
        """
        normalized = command.strip().lower()
        if normalized in EXIT_COMMANDS:
            self._console.print("[cyan]Goodbye! Keep coding. 👋[/cyan]")
            return False
        if normalized == "/help":
            self.show_help()
        elif normalized == "/clear":
            self._service.clear_history(self._session_id)
            self._console.print("[yellow]Conversation history cleared.[/yellow]")
        else:
            self._console.print(
                f"[red]Unknown command:[/red] {command}. Type [bold]/help[/bold] for the list."
            )
        return True

    def process_input(self, text: str) -> bool:
        """Route one line typed by the user.

        Args:
            text: Raw user input.

        Returns:
            False when the chat must end, True to keep running.
        """
        text = text.strip()
        # Empty input would waste an API call; just remind the user what to do.
        if not text:
            self._console.print("[dim]Please type a question (or /help).[/dim]")
            return True
        if text.startswith("/"):
            return self.handle_command(text)
        self.answer(text)
        return True

    def answer(self, question: str) -> None:
        """Ask the service and render the answer while it is being streamed.

        Args:
            question: User question.
        """
        chunks = self._service.stream(self._session_id, question, interface="cli")
        self._console.print(ASSISTANT_LABEL)
        try:
            # A spinner covers the wait for the first token (the slowest part)...
            with self._console.status("[cyan]Thinking...[/cyan]", spinner="dots"):
                answer = next(chunks, "")

            # ...then the Markdown is re-rendered as new chunks arrive, so code
            # blocks get syntax highlighting while the text is still streaming.
            with Live(
                Markdown(answer),
                console=self._console,
                refresh_per_second=12,
                vertical_overflow="visible",
            ) as live:
                for chunk in chunks:
                    answer += chunk
                    live.update(Markdown(answer))
        except ChatbotError as exc:
            # LLM failures, question too long, conversation limit...: the technical
            # details were logged by the service; show a friendly text.
            self._console.print(f"[bold red]⚠ {exc.user_message}[/bold red]")
        else:
            self._warn_if_near_limit()
        self._console.print()

    def _warn_if_near_limit(self) -> None:
        """Warn when the conversation is close to its size limit (80% or more)."""
        usage = self._service.get_usage(self._session_id)
        if usage.near_limit:
            self._console.print(
                f"[yellow]⚠ This conversation uses {usage.percent}% of its maximum size. "
                "Type /clear soon to start a new one.[/yellow]"
            )

    # --- Main loop ----------------------------------------------------------------

    def run(self, read_input: Callable[[str], str] | None = None) -> None:
        """Run the interactive loop until the user exits.

        Args:
            read_input: Function used to read a line (defaults to `Console.input`).
        """
        reader = read_input or self._console.input
        self.show_welcome()
        while True:
            try:
                keep_running = self.process_input(reader(PROMPT))
            except (KeyboardInterrupt, EOFError):
                # Ctrl+C / Ctrl+D must exit cleanly, without a traceback.
                self._console.print("\n[cyan]Goodbye! Keep coding. 👋[/cyan]")
                break
            if not keep_running:
                break


def main(console: Console | None = None) -> int:
    """Entry point of `python -m app.cli`.

    Args:
        console: Rich console (injectable for tests).

    Returns:
        The process exit code (0 on success, 1 on configuration error).
    """
    console = console or Console()
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings)

    try:
        service = create_chat_service(settings)
    except MissingAPIKeyError as exc:
        # Clear guidance instead of a stack trace.
        console.print(Panel(exc.user_message, title="Configuration error", border_style="red"))
        return 1

    ChatCLI(service, console=console).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
