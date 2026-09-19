from sqlalchemy import inspect
from app.data.database import engine

inspector = inspect(engine)
columns = inspector.get_columns("conversation_messages")
for c in columns:
    print(f"Column: {c['name']} - Type: {c['type']} - Nullable: {c['nullable']} - Default: {c['default']}")
