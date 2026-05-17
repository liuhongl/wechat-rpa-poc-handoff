# No-MsgAudit Desktop Agent P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add the first standard desktop-agent layer for the no-message-audit path: `WeComEvent -> ReplyJob -> SendPlan`.

**Architecture:** Keep the existing POC planners intact and add a focused module for the no-message-audit desktop agent contracts. The module adapts GUI snapshot records into standard events, reuses existing multi-group reply planning, and converts reply jobs into safe draft-first send plans.

**Tech Stack:** Python dataclasses, existing `app.member_assistant_poc` helpers, `unittest`, CLI scripts.

---

## File Structure

- Create `app/no_msgaudit_desktop_agent.py`
  - Owns standard no-message-audit data contracts and pure conversion helpers.
- Create `scripts/no_msgaudit_desktop_agent_poc.py`
  - Runs the standard chain from GUI snapshot to events, reply jobs, and send plans.
- Create `tests/test_no_msgaudit_desktop_agent.py`
  - Covers pure helpers and CLI dry-run behavior.
- Modify `docs/NO_MSGAUDIT_DESKTOP_AGENT_DESIGN.md`
  - Mark P0 interface alignment as completed and point to the POC script.

## Task 1: Add Standard Desktop Agent Contracts

**Files:**
- Create: `tests/test_no_msgaudit_desktop_agent.py`
- Create: `app/no_msgaudit_desktop_agent.py`

- [x] **Step 1: Write the failing tests**

Add tests that import `WeComEvent`, `build_wecom_events_from_ui_snapshot`, `wecom_event_to_plain_text_record`, `reply_job_to_send_plan`, and `send_plan_to_dict`.

Expected behaviors:

```python
def test_builds_standard_wecom_events_from_gui_snapshot():
    targets = [GroupReplyTarget(roomid="wr_auto_loan_group", chat_name="汽车贷款小助手")]
    events = build_wecom_events_from_ui_snapshot(
        "汽车贷款小助手 [有人@我] sky: 需要经营证明吗 @刘红利",
        group_targets=targets,
        assistant_name="刘红利",
        detected_at="2026-05-17T10:00:00+08:00",
        raw_snapshot_ref="snapshot-1",
    )
    assert events[0].event_id == "ui:汽车贷款小助手:sky:需要经营证明吗 @刘红利"
    assert events[0].source == "desktop_ui"
    assert events[0].chat_name == "汽车贷款小助手"
    assert events[0].sender_name == "sky"
    assert events[0].assistant_name == "刘红利"
    assert events[0].confidence == 1.0
```

```python
def test_converts_wecom_event_to_existing_plain_text_record():
    event = WeComEvent(
        event_id="ui:汽车贷款小助手:sky:需要经营证明吗 @刘红利",
        source="desktop_ui",
        chat_name="汽车贷款小助手",
        sender_name="sky",
        content="需要经营证明吗 @刘红利",
        assistant_name="刘红利",
        detected_at="2026-05-17T10:00:00+08:00",
        confidence=1.0,
        raw_snapshot_ref="snapshot-1",
    )
    record = wecom_event_to_plain_text_record(event, roomid_by_chat_name={"汽车贷款小助手": "wr_auto_loan_group"})
    assert record.msgid == event.event_id
    assert record.roomid == "wr_auto_loan_group"
    assert record.sender == "sky"
```

```python
def test_reply_job_to_send_plan_defaults_to_safe_draft_mode():
    job = MultiGroupReplyJob(
        roomid="wr_auto_loan_group",
        chat_name="汽车贷款小助手",
        source_msgid="ui:...",
        sender="sky",
        content="需要经营证明吗 @刘红利",
        reply_content="回复内容",
        matched_question="需要经营证明吗",
        score=1.0,
        handoff=False,
        question_content="需要经营证明吗",
        applescript="",
    )
    plan = reply_job_to_send_plan(job)
    assert plan.mode == "draft"
    assert plan.requires_operator_confirm is True
    assert send_plan_to_dict(plan)["send"] is False
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_no_msgaudit_desktop_agent
```

Expected: fail because `app.no_msgaudit_desktop_agent` does not exist.

- [x] **Step 3: Implement the minimal module**

Create dataclasses:

```python
@dataclass(frozen=True)
class WeComEvent: ...

@dataclass(frozen=True)
class WeComSendPlan: ...

@dataclass(frozen=True)
class WeComSendResult: ...
```

Add pure helpers:

```python
build_wecom_events_from_ui_snapshot(...)
wecom_event_to_plain_text_record(...)
reply_job_to_send_plan(...)
send_plan_to_dict(...)
```

- [x] **Step 4: Run tests to verify they pass**

Run:

```bash
.venv/bin/python -m unittest tests.test_no_msgaudit_desktop_agent
```

Expected: pass.

## Task 2: Add Standard Chain CLI

**Files:**
- Modify: `tests/test_no_msgaudit_desktop_agent.py`
- Create: `scripts/no_msgaudit_desktop_agent_poc.py`

- [x] **Step 1: Write the failing CLI test**

Add a subprocess test:

```python
def test_no_msgaudit_desktop_agent_poc_outputs_events_jobs_and_send_plans():
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "no_msgaudit_desktop_agent_poc.py"),
            "--assistant-name",
            "刘红利",
            "--ignore-state",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    assert '"type": "wecom_event"' in result.stdout
    assert '"type": "reply_job"' in result.stdout
    assert '"type": "send_plan"' in result.stdout
    assert '"mode": "draft"' in result.stdout
    assert '"send": false' in result.stdout
```

- [x] **Step 2: Run the CLI test to verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_no_msgaudit_desktop_agent
```

Expected: fail because the CLI script does not exist.

- [x] **Step 3: Implement the CLI script**

The script should:

```text
1. Load GUI snapshot text
2. Load group targets
3. Build WeComEvent rows
4. Convert events to PlainTextRecord rows
5. Reuse plan_multi_group_reply_jobs
6. Convert jobs to safe draft send plans
7. Print JSONL rows with type=wecom_event/reply_job/send_plan
8. Write the same rows to data/no_msgaudit_desktop_agent/desktop_agent_plan.jsonl by default
```

- [x] **Step 4: Run the CLI test to verify it passes**

Run:

```bash
.venv/bin/python -m unittest tests.test_no_msgaudit_desktop_agent
```

Expected: pass.

## Task 3: Update Docs and Verify

**Files:**
- Modify: `docs/NO_MSGAUDIT_DESKTOP_AGENT_DESIGN.md`

- [x] **Step 1: Update P0 checklist**

Mark the standard structures and GUI snapshot alignment as implemented, and add the CLI command:

```bash
.venv/bin/python scripts/no_msgaudit_desktop_agent_poc.py \
  --assistant-name "刘红利" \
  --ignore-state
```

- [x] **Step 2: Run full verification**

Run:

```bash
git diff --check
.venv/bin/python -m unittest discover -s tests
```

Expected: 34+ tests pass and no diff check output.

- [x] **Step 3: Commit**

Run:

```bash
git add app/no_msgaudit_desktop_agent.py scripts/no_msgaudit_desktop_agent_poc.py tests/test_no_msgaudit_desktop_agent.py docs/NO_MSGAUDIT_DESKTOP_AGENT_DESIGN.md docs/superpowers/plans/2026-05-17-no-msgaudit-desktop-agent-p0.md
git commit -m "feat: add no-msgaudit desktop agent contracts"
```
