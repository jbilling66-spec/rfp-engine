"""`engine serve` — the web shell, 127.0.0.1 only (B37/D1). The host is
NOT an argument: non-localhost binding arrives with A5's reverse proxy,
and until then the loopback bind is part of the auth story (header mode
is only safe behind a same-host proxy)."""

from pathlib import Path


def run_serve(args) -> int:
    import uvicorn

    from engine.web import create_app

    workspace = Path(args.workspace)
    if args.handoff:
        # P20/B81: the pilot switch — the PIPELINE lane's judgment goes
        # through the handoff seam (pending-calls/ request/response
        # files); assistant and advisor stay FakeCaller. Spends nothing:
        # a handoff call consumes an operator seat, never a key.
        from engine.llm import HandoffCaller, TracedCaller
        base = HandoffCaller(pending_dir=workspace / "pending-calls",
                             timeout=args.handoff_timeout)

        def make_caller(log):
            return TracedCaller(base.bind(pursuit_id=log.pursuit_id,
                                          run_id=log.run_id), log)
        app = create_app(workspace, make_caller=make_caller,
                         mode="handoff")
        print("pipeline: HANDOFF (pending-calls/ in the workspace; "
              "assistant and advisor stay FakeCaller)")
    else:
        app = create_app(workspace)
    if args.live_assistant:
        # P14/B63: the funded-demo switch, assistant lane ONLY — the
        # pipeline keeps its FakeCaller. LiveCaller's own construction
        # refuses without RFP_LIVE=1 + a key + priced models (B30(e)),
        # so the flag alone still spends nothing.
        from engine.cli.slice import ROOT
        from engine.llm.live import LiveCaller, load_env_file
        load_env_file(ROOT / ".env")  # the sanctioned .env read (B34(22))
        app.state.assistant_caller = LiveCaller()
        app.state.assistant_mode = "live"
        print("assistant: LIVE (session ceiling applies; "
              "pipeline stays FakeCaller)")
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


def register(sub) -> None:
    parser = sub.add_parser("serve", help="the web shell (127.0.0.1 only, "
                                          "FakeCaller default: zero spend)")
    parser.add_argument("--workspace", default="pursuits/web",
                        help="workspace directory holding the pursuits")
    parser.add_argument("--port", type=int, default=8400)
    parser.add_argument("--live-assistant", action="store_true",
                        help="live model for the ASSISTANT lane only "
                             "(requires RFP_LIVE=1; refuses otherwise)")
    parser.add_argument("--handoff", action="store_true",
                        help="handoff seam for the PIPELINE lane (P20/B81): "
                             "judgment through pending-calls/ files, "
                             "mode=handoff, zero spend")
    parser.add_argument("--handoff-timeout", type=float, default=900.0,
                        help="seconds to wait per judgment call before a "
                             "typed HandoffTimeout (handoff mode only)")
    parser.set_defaults(fn=run_serve)
