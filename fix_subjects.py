from app.data.database import managed_session
from app.data.models.chat import Conversation
import uuid

user_id = uuid.UUID('97df2f9d-f154-46c5-9d88-1e4af724e3a9')

with managed_session() as db:
    # Update conversations with subject_id=2 to subject_id=1
    updated = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.subject_id == 2
    ).all()
    print(f'Conversations to update: {len(updated)}')
    for c in updated:
        print(f'Updating {str(c.id)[:8]} "{c.title}" subject_id 2 -> 1')
        c.subject_id = 1
    db.flush()
    print('Done.')
