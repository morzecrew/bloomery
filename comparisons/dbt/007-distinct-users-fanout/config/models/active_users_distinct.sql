-- The project-authored reading of the distinct count, over the rows at the
-- grain asked for.
select count(distinct user_id) as active_users
from {{ ref('sessions') }}
