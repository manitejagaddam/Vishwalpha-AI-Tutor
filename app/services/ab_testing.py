import hashlib
import logging
from typing import Tuple, Optional
from sqlalchemy.orm import Session

from app.data.database import managed_session
from app.data.models.platform_ops import ABExperiment

logger = logging.getLogger(__name__)

def _assign_variant(user_id: str, experiment_name: str, traffic_split: int) -> bool:
    """
    Deterministically assigns a variant based on user_id and experiment name.
    Returns True for Variant A, False for Variant B.
    """
    if not user_id:
        # Fallback for anonymous users if any
        return True

    hash_input = f"{user_id}:{experiment_name}".encode('utf-8')
    # Use md5 as a fast, deterministic hash to spread users evenly
    hash_val = int(hashlib.md5(hash_input).hexdigest(), 16)
    # modulo 100 to get a 0-99 percentage bucket
    return (hash_val % 100) < traffic_split

def get_active_prompt(experiment_name: str, user_id: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Fetches the active A/B experiment by name and deterministically assigns the user
    to Variant A or Variant B based on the traffic_split.

    Returns:
        (prompt_template: str | None, ab_experiment_id: int | None)
    """
    try:
        with managed_session() as db:
            experiment = db.query(ABExperiment).filter(
                ABExperiment.name == experiment_name,
                ABExperiment.is_active == True
            ).first()

            if not experiment:
                return None, None

            # Determine variant
            is_variant_a = _assign_variant(str(user_id), experiment_name, experiment.traffic_split)

            template = experiment.variant_a_template if is_variant_a else experiment.variant_b_template
            
            return template, experiment.id

    except Exception as e:
        logger.error(f"Error fetching A/B experiment '{experiment_name}': {e}")
        return None, None
