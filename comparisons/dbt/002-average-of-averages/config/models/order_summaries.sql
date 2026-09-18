select order_id, average_item_price, cast(created_at as timestamp) as created_at
from {{ source('bronze', 'corpus__order_summaries') }}
