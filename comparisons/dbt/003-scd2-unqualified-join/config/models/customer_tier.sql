select customer_id, tier, valid_from, valid_to
from {{ source('silver', 'customer_tier') }}
