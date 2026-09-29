select order_id, line_no, discount, cast(created_at as timestamp) as created_at
from {{ source('bronze', 'corpus__order_items') }}
