from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from groq import Groq
from backend.config import GROQ_API_KEY, GROQ_MODEL
from backend.database import Conversation, Message


def get_conversation_memory(
    conversation: Conversation,
    db: Session,
    window_size: int = 8,
) -> Tuple[Optional[str], List[Dict[str, str]]]:
    """
    Returns (running_summary, recent_messages).
    - recent_messages: Last 8 messages verbatim.
    - running_summary: Concise summary of all older messages beyond the last 8.
    """
    # Fetch all messages in chronological order
    all_messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
        .all()
    )

    if not all_messages:
        return conversation.summary, []

    if len(all_messages) <= window_size:
        recent = [
            {"sender": m.sender, "content": m.content}
            for m in all_messages
        ]
        return conversation.summary, recent

    # Split into older vs recent window
    older_messages = all_messages[:-window_size]
    recent_messages = [
        {"sender": m.sender, "content": m.content}
        for m in all_messages[-window_size:]
    ]

    # Check if running summary needs update
    if older_messages:
        # Generate or update summary of older messages
        older_transcript = []
        for m in older_messages:
            role = "User" if m.sender == "user" else "Assistant"
            older_transcript.append(f"{role}: {m.content[:250]}")
        transcript_str = "\n".join(older_transcript)

        existing_summary = conversation.summary or ""
        update_prompt = (
            "Summarize the key facts, user inquiries, and topics covered in this earlier conversation excerpt "
            "into 2-3 dense sentences. Preserve specific names, document references, and numbers.\n\n"
            f"Existing Summary:\n{existing_summary}\n\n"
            f"New Earlier Messages to Incorporate:\n{transcript_str}\n\n"
            "Updated Summary:"
        )

        try:
            client = Groq(api_key=GROQ_API_KEY)
            res = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "You are a concise conversation memory summarizer."},
                    {"role": "user", "content": update_prompt},
                ],
                temperature=0.1,
                max_tokens=150,
            )
            new_summary = res.choices[0].message.content.strip()
            conversation.summary = new_summary
            db.commit()
            db.refresh(conversation)
        except Exception:
            pass

    return conversation.summary, recent_messages
