"""Chat with one or several Perspective Agents from the terminal."""

import argparse
import json
import uuid
from pathlib import Path

from llm_client import ROOT, create_client, read_settings
from perspective_agents import ChatSession, validate_bundle


def resolve_registry(path=None):
    if path:
        return Path(path)
    matches = list((ROOT/"data"/"processed").glob("*/03_agents/agents.json"))
    if len(matches) != 1:
        raise ValueError("Specify --registry PATH; expected exactly one built agent bundle.")
    return matches[0]


def show_result(result, session):
    for m in result["responses"]:
        agent = session.agents[m["sender_id"]]
        target = next(x for x in session.state["messages"] if x["message_id"] == m["reply_to"])
        print(f"\n[{m['message_id']} · {agent.agent_id} · {agent.name} → {target['sender_id']}]\n{m['text']}")
        if m["evidence"]:
            print(f"근거 댓글 {len(m['evidence'])}개 · /sources {m['message_id']}")
        for q in m["follow_up_questions"]:
            print(f"  이어서: {q}")
    for aid, error in result["errors"].items():
        print(f"[{aid}] 답변 실패: {error} · /retry {result['target_message_id']}")


def show_sources(session, mid=None):
    replies = [m for m in session.state["messages"] if m["role"] == "agent" and (mid is None or m["message_id"] == mid)]
    if not replies:
        print("근거를 볼 답변이 없습니다.")
        return
    if not replies[-1]["evidence"]:
        print("이 답변에는 연결된 원본 댓글이 없습니다. 추론 또는 자료 부족 설명인지 확인해주세요.")
        return
    for c in replies[-1]["evidence"]:
        print(f"\n{c.get('author','')} · {c['comment_id']}\n{c['text']}")
        if c.get("url"):
            print(c["url"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--list", action="store_true", help="list available agents without API calls")
    parser.add_argument("--agents", nargs="+", help="agent IDs, e.g. g1 g5")
    parser.add_argument("--session", type=Path, help="resume a saved room, or use a new file")
    parser.add_argument("--initial-opinion", default="", help="optional user's initial perspective")
    parser.add_argument("--ask", help="send one question and exit")
    parser.add_argument("--debate-rounds", type=int, default=0, choices=range(4))
    parser.add_argument("--provider", choices=("openai", "openrouter"))
    parser.add_argument("--model")
    args = parser.parse_args()
    if args.debate_rounds and not args.ask:
        parser.error("--debate-rounds is used with --ask; in interactive mode use /debate")
    try:
        registry = resolve_registry(args.registry)
        bundle = validate_bundle(json.loads(registry.read_text(encoding="utf-8")))
        if args.list:
            for a in bundle["agents"]:
                print(f"{a['agent_id']} · {a['name']} ({len(a['comments'])} comments)\n  {a['stance']}")
            return
        if not args.agents and not (args.session and args.session.exists()):
            parser.error("Choose --agents g1 (one-on-one) or --agents g1 g5 (group); use --list to inspect.")
        path = args.session or registry.parent/"sessions"/f"{uuid.uuid4().hex}.json"
        session = ChatSession(bundle, path, args.agents, args.initial_opinion)
        if args.debate_rounds and len(session.state["participants"]) < 2:
            parser.error("Debate requires at least two participants.")
        client = create_client(read_settings(), args.provider, args.model)
        recipients = list(session.state["participants"])
        print(f"대화 기록: {path}\n참여 에이전트: {', '.join(recipients)}")
        if args.ask:
            result = session.ask(args.ask, client, recipients)
            show_result(result, session)
            if result["errors"]:
                parser.exit(1, "Some agents failed; successful replies and the question were saved for retry.\n")
            for result in session.debate(client, args.debate_rounds, recipients) if args.debate_rounds else []:
                show_result(result, session)
                if result["errors"]:
                    parser.exit(1, "Discussion stopped after an agent failure; saved replies can be resumed.\n")
            return
        print("질문을 입력하세요. /to g1,g5 · /sources [메시지ID] · /debate [1~3] · /retry 메시지ID · /history · /exit")
        while True:
            try:
                text = input("\n나> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n대화를 저장했습니다.")
                break
            if not text:
                continue
            if text in ("/exit", "/quit"):
                break
            try:
                if text.startswith("/to "):
                    selected = text[4:].replace(",", " ").split()
                    session.check_recipients(selected, session.state["participants"])
                    recipients = selected
                    print("다음 질문 대상: "+", ".join(selected))
                elif text.startswith("/sources"):
                    parts = text.split()
                    show_sources(session, parts[1] if len(parts)>1 else None)
                elif text.startswith("/debate"):
                    parts = text.split()
                    for result in session.debate(client, int(parts[1]) if len(parts)>1 else 1, recipients):
                        show_result(result, session)
                elif text.startswith("/retry "):
                    show_result(session.answer(text.split()[1], recipients, client), session)
                elif text == "/history":
                    for m in session.state["messages"]:
                        print(f"{m['message_id']} [{m['sender_id']}] {m['text']}")
                elif text.startswith("/"):
                    print("사용 가능한 명령: /to /sources /debate /retry /history /exit")
                else:
                    show_result(session.ask(text, client, recipients), session)
            except (ValueError, OSError) as exc:
                print(f"처리하지 못했습니다: {exc}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
