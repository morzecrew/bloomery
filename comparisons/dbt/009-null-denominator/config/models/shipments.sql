select shipment_id, carrier_cost, parcels, shipped_on
from {{ source('bronze', 'corpus__shipments') }}
