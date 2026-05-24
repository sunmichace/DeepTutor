"""Mock interview CLI commands."""

from __future__ import annotations

import typer

from deeptutor.app import DeepTutorApp, TurnRequest

from .common import maybe_run, run_turn_and_render


def register(app: typer.Typer) -> None:
    @app.command("start")
    def start_interview(
        message: str = typer.Argument(
            "开始模拟面试",
            help="Optional opening message for the interview turn.",
        ),
        session: str | None = typer.Option(None, "--session", help="Existing session id."),
        exam_type: str = typer.Option("公考面试", "--exam-type", help="Exam type."),
        position: str = typer.Option("", "--position", help="Target position."),
        question_type: str = typer.Option("综合分析", "--question-type", help="Interview question type."),
        difficulty: str = typer.Option("medium", "--difficulty", help="Difficulty: easy | medium | hard."),
        language: str = typer.Option("zh", "--language", "-l", help="Response language."),
        fmt: str = typer.Option("rich", "--format", "-f", help="Output format: rich | json."),
    ) -> None:
        """Start a mock interview and receive the first question."""
        request = _build_interview_request(
            message=message,
            session=session,
            language=language,
            mode="start",
            fmt=fmt,
            config={
                "exam_type": exam_type,
                "position": position,
                "question_type": question_type,
                "difficulty": difficulty,
            },
        )
        maybe_run(run_turn_and_render(app=DeepTutorApp(), request=request, fmt=fmt))

    @app.command("answer")
    def answer_interview(
        answer: str = typer.Argument(..., help="Candidate answer text."),
        session: str = typer.Option(..., "--session", help="Session id returned by `interview start`."),
        language: str = typer.Option("zh", "--language", "-l", help="Response language."),
        fmt: str = typer.Option("rich", "--format", "-f", help="Output format: rich | json."),
    ) -> None:
        """Submit an answer for the active mock interview session."""
        request = _build_interview_request(
            message=answer,
            session=session,
            language=language,
            mode="answer",
            fmt=fmt,
            config={"answer": answer},
        )
        maybe_run(run_turn_and_render(app=DeepTutorApp(), request=request, fmt=fmt))

    @app.command("profile")
    def profile(
        session: str = typer.Option(..., "--session", help="Session/user id to inspect."),
        language: str = typer.Option("zh", "--language", "-l", help="Response language."),
        fmt: str = typer.Option("json", "--format", "-f", help="Output format: rich | json."),
    ) -> None:
        """Show the interview learner profile and stored sessions."""
        request = _build_interview_request(
            message="查看面试画像",
            session=session,
            language=language,
            mode="profile",
            fmt=fmt,
            config={},
        )
        maybe_run(run_turn_and_render(app=DeepTutorApp(), request=request, fmt=fmt))

    @app.command("cancel")
    def cancel(
        session: str = typer.Option(..., "--session", help="Session id to cancel."),
        language: str = typer.Option("zh", "--language", "-l", help="Response language."),
        fmt: str = typer.Option("rich", "--format", "-f", help="Output format: rich | json."),
    ) -> None:
        """Cancel the active mock interview session."""
        request = _build_interview_request(
            message="取消模拟面试",
            session=session,
            language=language,
            mode="cancel",
            fmt=fmt,
            config={},
        )
        maybe_run(run_turn_and_render(app=DeepTutorApp(), request=request, fmt=fmt))


def _build_interview_request(
    *,
    message: str,
    session: str | None,
    language: str,
    mode: str,
    fmt: str,
    config: dict[str, str],
) -> TurnRequest:
    if fmt not in {"rich", "json"}:
        raise typer.BadParameter("--format must be `rich` or `json`.")
    return TurnRequest(
        content=message,
        capability="mock_interview",
        session_id=session,
        language=language,
        config={"mode": mode, **config},
    )
