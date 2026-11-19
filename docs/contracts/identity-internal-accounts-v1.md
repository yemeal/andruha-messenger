# Internal Identity account lookup v1

`POST /internal/v1/accounts/lookup` is a private service-to-service endpoint.
The API Gateway does not route `/internal/`. It requires `X-Service-Token`,
compared in constant time with `IDENTITY_INTERNAL_API_TOKEN`. Missing runtime
configuration fails closed with 503; an absent/incorrect credential returns 401.

Request (1..100 UUIDs, duplicate inputs permitted):

```json
{"userIds":["01995140-0000-7000-8000-000000000001","01995140-0000-7000-8000-000000000002"]}
```

Response:

```json
{"registeredUserIds":["01995140-0000-7000-8000-000000000001"]}
```

Only completed Identity accounts for which `User.can_authenticate` is true are
returned. Results preserve first-request order without duplicates. Absent,
pending and DISABLED Identity accounts are omitted. A Profile row alone never
qualifies. Profile DISABLED/BLOCKED lifecycle does not add a messaging ban.
No credentials, email, role or profile attributes are returned. Responses are
`Cache-Control: no-store`; this is an eligibility lookup, not a profile API.

Schemas: `contracts/identity/http/accounts-lookup-{request,response}.v1.schema.json`.
The route is excluded from the public Identity OpenAPI. Existing auth APIs and
identity.events.v1 are compatible. Consumers use the v1 route and reject unknown
or malformed response fields rather than treating them as missing accounts.

Messages uses `HTTPRegisteredUsers`: bounded 100-ID requests, a finite deadline
per request, a bounded response body and an explicit distinction between
`UserNotRegisteredError` and `IdentityUnavailableError` (including bad service
credentials, timeout and unavailable Identity). Accepted command recovery does
not repeat external eligibility checks. Ordinary send/read will use local JWT
verification and current membership when those runtime roles are implemented.
