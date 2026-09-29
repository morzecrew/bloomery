select session_id, user_id, cast(session_day as timestamp) as session_day
from {{ source('bronze', 'corpus__sessions') }}
