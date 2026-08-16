# Andruha Messenger MVP - Sequence Diagrams

Статус: design baseline для MVP.

Этот документ описывает не все мыслимые сбои распределенной системы, а полный
набор классов отказов, которые входят в согласованный MVP:

1. validation и business rejection;
2. authentication и authorization failure;
3. duplicate request и broker redelivery;
4. dependency unavailable;
5. timeout с неоднозначным результатом;
6. process crash между durable effect и публикацией ответа;
7. offline client и потеря WebSocket-соединения;
8. poison message и DLQ.

## 1. Границы и инварианты

- MVP поддерживает только диалоги 1:1.
- HTTP-трафик маршрутизирует API Gateway, но бизнес-логики в нем нет.
- Identity, Profile, Messages и WebSocket Gateway проверяют RS256 access token
  локально. Синхронного запроса в Identity на каждый вызов нет.
- Credentials хранятся в Identity PostgreSQL.
- Целевая модель refresh-сессий хранится в Cassandra Session Store; Valkey
  используется только как idempotency guard.
- Messages and Dialogues Service хранит query-driven проекции в Cassandra.
- Kafka работает в режиме at-least-once. Consumers подтверждают offset только
  после durable business effect и обязательной публикации результата.
- Exactly-once не заявляется. Повторы безопасны благодаря idempotency keys,
  client_message_id, event_id и монотонным версиям состояния.
- SENT означает durable запись сообщения в Cassandra.
- DELIVERED устанавливается только после явного ACK от клиента получателя.
- READ устанавливается только после явного ACK, когда сообщение показано
  пользователю. READ поглощает DELIVERED.
- Typing не сохраняется и не переигрывается.
- Notification Service, mobile push, группы, поиск и cold storage не входят в MVP.

## 2. Цветовая легенда

| Цвет | Значение |
|---|---|
| Синий | Client, Load Balancer, API Gateway |
| Зеленый | Application service или worker |
| Фиолетовый | Durable database или object storage |
| Оранжевый | Kafka, Valkey и transient coordination |
| Светло-зеленый фон | Happy path |
| Светло-желтый фон | Retry, timeout или неоднозначный результат |
| Светло-красный фон | Failure path |

## 3. Каталог сценариев

| ID | Use case | Основные failure paths |
|---|---|---|
| AUTH-01 | Registration и создание профиля | invalid payload, duplicate email, PostgreSQL down, outbox lag, duplicate event |
| AUTH-02 | Login | invalid credentials, user changed, session store down, lost response |
| AUTH-03 | Refresh rotation | cached retry, concurrent retry, token reuse, LWT timeout, Valkey/Cassandra down |
| AUTH-04 | Logout | missing token, already revoked, session store down |
| AUTH-05 | Current identity | invalid JWT, disabled user, PostgreSQL down |
| WS-01 | WebSocket connect и lifecycle | invalid JWT, registry down, token expiry, gateway crash |
| PROF-01 | Read и edit profile | 401, validation, version conflict, PostgreSQL down |
| DLG-01 | Create/get 1:1 dialog | self-dialog, unknown user, duplicate create, LWT timeout, partial projection |
| DLG-02 | Dialog list и message history | invalid cursor, forbidden dialog, bucket boundary, Cassandra down |
| MSG-01 | Accept send command | malformed frame, unauthorized, rate limit, Kafka down, duplicate request |
| MSG-02 | Persist и fan-out message | non-member, Cassandra down, crash before event, duplicate event, recipient offline |
| RCPT-01 | Delivered/read receipts | out-of-order ACK, duplicate ACK, unauthorized ACK, dependency failure |
| TYP-01 | Typing | throttling, Valkey down, disconnect, offline recipient |
| SYNC-01 | Reconnect и catch-up | expired token, invalid cursor, Cassandra down, concurrent realtime event |
| OBJ-01 | Upload и finalize | invalid media, expired URL, interrupted upload, checksum mismatch, lost response |
| OBJ-02 | Media attachment и download | foreign object, not ready, Storage down, forbidden download |
| AVT-01 | Set avatar | wrong MIME, foreign object, version conflict, dependency failure |

---

## AUTH-01. Registration и асинхронное создание профиля

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Client and Edge
        actor C as Client / Browser
        participant API as API Gateway
    end
    box rgb(232, 245, 233) Identity
        participant ID as Identity Service
        participant IR as Identity Outbox Relay
    end
    box rgb(243, 229, 245) Durable Storage
        participant IPG as Identity PostgreSQL
        participant PPG as Profile PostgreSQL
    end
    box rgb(255, 243, 224) Messaging
        participant K as Kafka
    end
    box rgb(232, 245, 233) Profile
        participant PC as Profile Consumer
    end

    C->>+API: POST /api/v1/auth/register<br/>{email, password}
    API->>+ID: Forward request + request_id
    ID->>ID: Normalize email<br/>validate password policy

    alt Invalid payload
        rect rgb(255, 235, 238)
            ID-->>API: 422 validation_error
            API-->>C: 422 validation_error
        end
    else Valid payload
        ID->>ID: Argon2id hash outside DB transaction
        ID->>+IPG: BEGIN<br/>INSERT user ON CONFLICT(email) DO NOTHING
        alt Email already exists
            rect rgb(255, 235, 238)
                IPG-->>ID: conflict / no inserted row
                ID->>IPG: ROLLBACK
                ID-->>API: 409 auth.email_already_exists
                API-->>C: 409 auth.email_already_exists
            end
        else PostgreSQL unavailable
            rect rgb(255, 235, 238)
                IPG--xID: connection error / timeout
                ID-->>API: 503 dependency_unavailable
                API-->>C: 503 + Retry-After
            end
        else User inserted
            rect rgb(232, 245, 233)
                ID->>IPG: INSERT outbox identity.user_registered.v1<br/>{event_id, user_id, locale, created_at}
                IPG-->>-ID: COMMIT user + outbox
                ID-->>-API: 201 {user_id}
                API-->>-C: 201 {user_id}
            end
        end
    end

    par Outbox relay runs independently
        loop Until Kafka accepts or record is quarantined
            IR->>+IPG: Claim due outbox row<br/>FOR UPDATE SKIP LOCKED
            IPG-->>-IR: claimed event
            IR->>+K: Publish identity.user_registered.v1<br/>key=user_id
            alt Kafka acknowledged
                rect rgb(232, 245, 233)
                    K-->>IR: broker ACK
                    IR->>IPG: Mark SUCCESS
                end
            else Kafka unavailable
                rect rgb(255, 248, 225)
                    K--xIR: timeout / unavailable
                    IR->>IPG: Return to PENDING<br/>backoff + jitter
                    Note over IR,K: Registration remains committed.<br/>Profile creation is delayed, not lost.
                end
            end
        end
    and Profile consumer handles event
        K->>+PC: identity.user_registered.v1
        PC->>+PPG: BEGIN<br/>INSERT processed_event IF ABSENT<br/>INSERT default profile IF ABSENT
        alt First delivery
            rect rgb(232, 245, 233)
                PPG-->>PC: COMMIT
                PC-->>K: ACK offset
            end
        else Duplicate delivery
            rect rgb(255, 248, 225)
                PPG-->>PC: processed_event already exists
                PC-->>K: ACK without duplicate profile
            end
        else Profile PostgreSQL unavailable
            rect rgb(255, 235, 238)
                PPG--xPC: error / timeout
                PC-->>K: NACK / no offset commit
                Note over PC,K: Kafka redelivers after recovery.
            end
        end
    end

    opt Identity crashes after COMMIT but before 201
        rect rgb(255, 248, 225)
            Note over C,IPG: Client sees an ambiguous result.<br/>Retry returns email conflict, then user may proceed to login.<br/>Adding register Idempotency-Key is a post-MVP hardening option.
        end
    end
```

### AUTH-01 decisions

- User and outbox event commit atomically.
- Profile creation is eventually consistent and idempotent.
- Kafka or Profile failure does not roll back registration.
- A missing profile must be treated by Profile API as a temporary provisioning
  state, not as proof that Identity user does not exist.

---

## AUTH-02. Login и создание session family

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Client and Edge
        actor C as Client / Browser
        participant API as API Gateway
    end
    box rgb(232, 245, 233) Identity
        participant ID as Identity Service
    end
    box rgb(243, 229, 245) Durable Storage
        participant IPG as Identity PostgreSQL
        participant SS as Cassandra Session Store
    end

    C->>+API: POST /api/v1/auth/login<br/>{email, password}
    API->>+ID: Forward request + request_id
    ID->>+IPG: SELECT user BY normalized_email
    IPG-->>-ID: user record or null

    critical Constant-work credential verification
        ID->>ID: If user missing: dummy Argon2id<br/>Else: verify stored Argon2id hash<br/>Apply bounded crypto jitter
    option Hash worker saturated
        rect rgb(255, 235, 238)
            ID-->>API: 503 auth_capacity_exhausted<br/>Retry-After
            API-->>C: 503 + Retry-After
        end
    end

    alt Missing, disabled, or wrong password
        rect rgb(255, 235, 238)
            ID-->>API: 401 auth.invalid_credentials
            API-->>C: 401 generic error
            Note over C,ID: Response does not reveal whether email exists.
        end
    else Credentials valid
        ID->>+IPG: BEGIN<br/>SELECT user FOR UPDATE by id
        alt User changed during password verification
            rect rgb(255, 235, 238)
                IPG-->>ID: missing / disabled / hash changed
                ID->>IPG: ROLLBACK
                ID-->>API: 401 auth.invalid_credentials
                API-->>C: 401 generic error
            end
        else User still active
            rect rgb(232, 245, 233)
                IPG-->>-ID: active user + role + auth_version
                ID->>ID: Generate session_id, token_id, random secret<br/>Compute SHA-256 digest
                ID->>+SS: INSERT session family IF NOT EXISTS<br/>TTL=absolute session lifetime
                alt Session stored
                    SS-->>ID: APPLIED
                    ID->>ID: Issue short-lived RS256 access token<br/>sub, role, sid, auth_version
                    ID-->>API: 204 Set-Cookie<br/>access_token + refresh_token
                    API-->>C: 204 Set-Cookie + Cache-Control:no-store
                else Session Store unavailable
                    rect rgb(255, 235, 238)
                        SS--xID: timeout / unavailable
                        ID-->>API: 503 session_store_unavailable
                        API-->>C: 503 + Retry-After<br/>No cookies
                    end
                end
            end
        end
    end

    opt Response lost after session was stored
        rect rgb(255, 248, 225)
            Note over C,SS: Client may safely repeat login.<br/>A second independent session may be created.<br/>The first expires or is revoked by session management.
        end
    end
```

### AUTH-02 decisions

- Argon2id never holds a database transaction or connection.
- No token is returned unless session state is durably stored.
- Creating two sessions after an ambiguous login retry is acceptable for MVP.

---

## AUTH-03. Refresh rotation, safe retry и replay detection

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Client and Edge
        actor C as Client / Browser
        participant API as API Gateway
    end
    box rgb(232, 245, 233) Identity
        participant EP as Auth HTTP Entrypoint
        participant ID as Identity App Service
    end
    box rgb(255, 243, 224) Coordination
        participant V as Valkey Idempotency Guard
    end
    box rgb(243, 229, 245) Durable Storage
        participant SS as Cassandra Session Store
    end

    C->>+API: POST /api/v1/auth/refresh<br/>Cookie=RT_1, Idempotency-Key=K1
    API->>+EP: Forward cookie + K1
    EP->>EP: Digest request payload<br/>scope key=auth:refresh:K1
    EP->>+V: Atomic acquire/read(K1, payload_hash)

    alt Same token + same key, completed within window
        rect rgb(232, 245, 233)
            V-->>EP: COMPLETED + cached TokenPair_2
            Note over EP,ID: Do not call rotation again.
            EP-->>API: 204 Set-Cookie TokenPair_2
            API-->>C: 204 cached response
        end
    else Same key is currently processing
        rect rgb(255, 248, 225)
            V-->>EP: IN_PROGRESS
            EP-->>API: 423 auth.refresh_in_progress<br/>Retry-After
            API-->>C: 423<br/>retry same K1
        end
    else Same key + different payload
        rect rgb(255, 235, 238)
            V-->>EP: PAYLOAD_MISMATCH
            EP-->>API: 409 idempotency_payload_mismatch
            API-->>C: 409<br/>do not retry with K1
        end
    else Valkey unavailable
        rect rgb(255, 235, 238)
            V--xEP: unavailable / timeout
            EP-->>API: 503 idempotency_store_unavailable
            API-->>C: 503 + Retry-After
            Note over EP,SS: Fail closed. Rotation is not invoked<br/>without safe-retry protection.
        end
    else First request owns K1
        V-->>-EP: ACQUIRED
        EP->>+ID: rotate(RT_1)
        ID->>ID: Parse non-secret session_id/token_id<br/>Digest secret

        critical Atomic compare-and-set rotation
            ID->>+SS: LWT IF active AND current_token_id=T1<br/>AND digest=SHA256(RT_1)<br/>SET current_token=T2, extend idle expiry
            SS-->>-ID: applied + session snapshot
        option LWT timeout with unknown outcome
            rect rgb(255, 248, 225)
                SS--xID: timeout / WriteTimeout
                ID->>SS: Resolve by SERIAL read of session
                alt Session already points to T2 from this request
                    SS-->>ID: rotation committed
                    ID->>ID: Reconstruct stored pending result
                else Session still points to T1
                    SS-->>ID: rotation not applied
                    ID->>SS: Retry bounded LWT
                else State cannot be proven
                    SS-->>ID: unknown / unavailable
                    ID-->>EP: 503 refresh_result_unknown
                    EP->>V: Keep short-lived IN_PROGRESS marker
                    EP-->>API: 503 + Retry-After
                    API-->>C: Retry same token + same K1
                end
            end
        end

        alt LWT applied - happy path
            rect rgb(232, 245, 233)
                ID->>ID: Issue AccessToken_2 + opaque RT_2
                ID-->>EP: TokenPair_2
                EP->>V: Store COMPLETED TokenPair_2 with TTL
                alt Cache write succeeded
                    V-->>EP: stored
                else Cache write failed after durable rotation
                    rect rgb(255, 248, 225)
                        V--xEP: timeout
                        Note over EP,V: Response may still be returned.<br/>If it is lost, next retry may look like reuse.<br/>Production hardening stores recoverable<br/>rotation result in Session Store.
                    end
                end
                EP-->>API: 204 Set-Cookie AccessToken_2 + RT_2
                API-->>C: 204 + no-store
            end
        else Token missing, expired, revoked, or malformed
            rect rgb(255, 235, 238)
                SS-->>ID: NOT_APPLIED + inactive/not_found
                ID-->>EP: InvalidRefreshToken
                EP->>V: Store terminal 401 result for K1
                EP-->>API: 401 + Clear-Cookie
                API-->>C: 401<br/>login required
            end
        else RT_1 was already consumed with another key
            rect rgb(255, 235, 238)
                SS-->>ID: NOT_APPLIED + prior token recognized
                ID->>SS: LWT revoke session family IF active
                SS-->>ID: revoked or already revoked
                ID-->>EP: RefreshTokenReused
                EP->>V: Store terminal 401 result for K1
                EP-->>API: 401 + Clear-Cookie
                API-->>C: 401<br/>login required
                Note over ID,SS: Reuse is treated as possible token theft.
            end
        else Cassandra unavailable before a proven result
            rect rgb(255, 235, 238)
                SS--xID: unavailable
                ID-->>EP: 503 session_store_unavailable
                EP->>V: Release or expire K1 ownership
                EP-->>API: 503 + Retry-After
                API-->>C: Retry same RT_1 + same K1
            end
        end
    end

    opt HTTP response is lost
        rect rgb(255, 248, 225)
            C->>API: Retry RT_1 + same K1
            Note over C,V: COMPLETED cache returns the exact same TokenPair_2.<br/>Business rotation is not executed twice.
        end
    end
```

### AUTH-03 critical invariant

The durable store must retain enough data to recover TokenPair_2 after an
ambiguous LWT or a failed Valkey result write. Otherwise a legitimate retry can
be misclassified as theft. A practical model stores an encrypted pending
rotation result or a short-lived recoverable next-token secret in the same
session partition.

---

## AUTH-04. Idempotent logout

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Client and Edge
        actor C as Client / Browser
        participant API as API Gateway
    end
    box rgb(232, 245, 233) Identity
        participant ID as Identity Service
    end
    box rgb(243, 229, 245) Durable Storage
        participant SS as Cassandra Session Store
    end

    C->>+API: POST /api/v1/auth/logout<br/>Cookie=refresh_token?
    API->>+ID: Forward request

    alt Refresh cookie missing or malformed
        rect rgb(255, 248, 225)
            ID-->>API: 204 Clear-Cookie
            API-->>C: 204 Clear-Cookie
            Note over C,ID: Logout does not reveal session existence.
        end
    else Refresh cookie present
        ID->>ID: Parse session_id and digest secret
        ID->>+SS: LWT revoke session IF active
        alt Session revoked now
            rect rgb(232, 245, 233)
                SS-->>ID: APPLIED
                ID-->>API: 204 Clear-Cookie
                API-->>C: 204 Clear-Cookie
            end
        else Session missing or already revoked
            rect rgb(255, 248, 225)
                SS-->>ID: NOT_APPLIED
                ID-->>API: 204 Clear-Cookie
                API-->>C: 204 Clear-Cookie
            end
        else Cassandra unavailable
            rect rgb(255, 235, 238)
                SS--xID: unavailable / timeout
                ID-->>API: 503 session_store_unavailable
                API-->>C: 503 + Retry-After
                Note over C,ID: Cookies are not cleared until durable revoke<br/>unless product explicitly chooses local-only logout.
            end
        end
    end
```

### AUTH-04 decision

MVP uses fail-closed logout: if durable revocation cannot be confirmed, the
client receives 503 and retries. This avoids showing successful logout while
the refresh token is still usable.

---

## WS-01. WebSocket connect, heartbeat и connection lifecycle

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Client and Edge
        actor C as Client / Browser
        participant LB as Load Balancer
    end
    box rgb(232, 245, 233) Realtime
        participant WS as WebSocket Gateway
    end
    box rgb(255, 243, 224) Coordination
        participant V as Valkey Connection Registry
    end

    C->>+LB: GET /ws Upgrade:websocket<br/>Cookie=access_token
    LB->>+WS: Forward upgrade request
    WS->>WS: Verify RS256 signature locally<br/>iss, aud, exp, token_type, sub

    alt Token missing, invalid, or expired
        rect rgb(255, 235, 238)
            WS-->>LB: Reject handshake 401
            LB-->>C: 401 auth.invalid_token
        end
    else Token valid
        WS->>WS: Allocate connection_id<br/>bind authenticated user_id
        WS->>+V: Register user_id -><br/>{gateway_id, connection_id}<br/>EX heartbeat_ttl
        alt Registry unavailable
            rect rgb(255, 235, 238)
                V--xWS: timeout / unavailable
                WS-->>LB: 503 / close 1013
                LB-->>C: Retry with backoff
                Note over C,WS: Fail closed: an unregistered connection<br/>cannot receive cross-instance events reliably.
            end
        else Registered
            rect rgb(232, 245, 233)
                V-->>-WS: OK
                WS-->>-LB: 101 Switching Protocols
                LB-->>-C: WebSocket established
                WS-->>C: connection.ready<br/>{connection_id, server_time, heartbeat_interval}
            end

            loop Every heartbeat interval
                WS-->>C: ping
                alt pong received before timeout
                    C-->>WS: pong
                    WS->>V: Extend connection TTL
                else pong missing
                    rect rgb(255, 248, 225)
                        WS-->>C: close 1001 heartbeat_timeout
                        WS->>V: Delete connection registration
                    end
                end
            end

            opt Access token approaches exp
                WS-->>C: auth.expiring {expires_at}
                alt Client refreshes and reconnects
                    rect rgb(232, 245, 233)
                        C->>C: HTTP refresh<br/>open replacement socket
                        Note over C,WS: Old socket closes only after<br/>new connection is ready.
                    end
                else Token reaches exp
                    rect rgb(255, 235, 238)
                        WS-->>C: close 4401 auth.token_expired
                        WS->>V: Delete connection registration
                    end
                end
            end

            alt Graceful client disconnect
                C-->>WS: close 1000
                WS->>V: Delete connection registration
            else Network loss
                rect rgb(255, 248, 225)
                    Note over C,V: TCP disappears without cleanup.<br/>Registry record expires by TTL.
                end
            else Gateway process crashes
                rect rgb(255, 248, 225)
                    WS--xC: connection dropped
                    Note over C,V: TTL removes stale routing.<br/>Client reconnects with jitter.
                end
            end
        end
    end
```

### WS-01 decisions

- Multiple concurrent connections per user are allowed.
- The access token is validated once during handshake and its expiry schedules
  mandatory reconnect.
- Connection registry is routing metadata, not presence history.
- Sticky sessions are not needed after the WebSocket handshake because the TCP
  connection stays attached to one Gateway instance.

---

## PROF-01. Read and edit own profile

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Client and Edge
        actor C as Client / Browser
        participant API as API Gateway
    end
    box rgb(232, 245, 233) Profile
        participant P as User Profile Service
    end
    box rgb(243, 229, 245) Durable Storage
        participant PG as Profile PostgreSQL
    end

    C->>+API: GET or PATCH /api/v1/profiles/me<br/>Cookie=access_token
    API->>+P: Forward request
    P->>P: Verify RS256 locally<br/>extract authenticated user_id

    alt Token invalid or expired
        rect rgb(255, 235, 238)
            P-->>API: 401 auth.invalid_token
            API-->>C: 401<br/>refresh required
        end
    else GET /profiles/me
        P->>+PG: SELECT profile BY user_id
        alt Profile exists
            rect rgb(232, 245, 233)
                PG-->>P: profile + version
                P-->>API: 200 profile<br/>ETag=version
                API-->>C: 200 profile
            end
        else Profile event is still delayed
            rect rgb(255, 248, 225)
                PG-->>P: null
                P->>PG: INSERT default profile IF ABSENT<br/>using JWT sub
                PG-->>P: created or concurrent row
                P-->>API: 200 default profile
                API-->>C: 200 default profile
                Note over P,PG: Lazy create repairs delayed<br/>identity.user_registered delivery.
            end
        else PostgreSQL unavailable
            rect rgb(255, 235, 238)
                PG--xP: unavailable / timeout
                P-->>API: 503 profile_store_unavailable
                API-->>C: 503 + Retry-After
            end
        end
    else PATCH /profiles/me
        P->>P: Validate display_name, bio, locale<br/>reject credential fields
        alt Payload invalid
            rect rgb(255, 235, 238)
                P-->>API: 422 validation_error
                API-->>C: 422 field errors
            end
        else Valid patch
            P->>+PG: UPDATE profile SET ... version=version+1<br/>WHERE user_id=sub AND version=If-Match
            alt Updated
                rect rgb(232, 245, 233)
                    PG-->>P: updated profile + new version
                    P-->>API: 200 profile<br/>ETag=new version
                    API-->>C: 200 updated profile
                end
            else Stale version
                rect rgb(255, 248, 225)
                    PG-->>P: zero rows
                    P->>PG: SELECT current profile
                    PG-->>P: current version
                    P-->>API: 409 profile.version_conflict<br/>current_version
                    API-->>C: Reload and merge
                end
            else PostgreSQL unavailable
                rect rgb(255, 235, 238)
                    PG--xP: unavailable / timeout
                    P-->>API: 503 profile_store_unavailable
                    API-->>C: 503 + Retry-After
                end
            end
        end
    end
```

### PROF-01 decisions

- Email, password, role and account status never belong to Profile Service.
- Valid JWT subject is sufficient for lazy creation of the caller's own profile.
- Concurrent edits are detected through version, not last-write-wins.

---

## DLG-01. Idempotent creation of a 1:1 dialog

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Client and Edge
        actor A as Client A
        participant API as API Gateway
    end
    box rgb(232, 245, 233) Application Services
        participant M as Messages and Dialogues Service
        participant P as User Profile Service
    end
    box rgb(243, 229, 245) Durable Storage
        participant C as Messages Cassandra
    end

    A->>+API: POST /api/v1/dialogs<br/>{peer_user_id}
    API->>+M: Forward request
    M->>M: Verify JWT locally<br/>caller_user_id = sub

    alt Invalid JWT
        rect rgb(255, 235, 238)
            M-->>API: 401 auth.invalid_token
            API-->>A: 401
        end
    else peer_user_id equals caller
        rect rgb(255, 235, 238)
            M-->>API: 422 dialog.self_not_allowed
            API-->>A: 422
        end
    else Candidate pair is valid
        M->>+P: HEAD /internal/v1/profiles/{peer_user_id}
        alt Peer does not exist
            rect rgb(255, 235, 238)
                P-->>M: 404
                M-->>API: 404 dialog.peer_not_found
                API-->>A: 404
            end
        else Profile Service unavailable
            rect rgb(255, 235, 238)
                P--xM: timeout / unavailable
                M-->>API: 503 peer_validation_unavailable
                API-->>A: 503 + Retry-After
            end
        else Peer exists
            P-->>-M: 204
            M->>M: pair_key=min(userA,userB)+max(userA,userB)<br/>generate candidate dialog_id

            critical Unique pair reservation
                M->>+C: LWT INSERT dialog_by_pair(pair_key, dialog_id)<br/>IF NOT EXISTS
                C-->>-M: applied or existing dialog_id
            option LWT timeout - result unknown
                rect rgb(255, 248, 225)
                    C--xM: WriteTimeout
                    M->>C: SERIAL read dialog_by_pair(pair_key)
                    alt Pair exists
                        C-->>M: committed dialog_id
                    else Pair absent
                        C-->>M: null
                        M->>C: Bounded retry of same reservation
                    else Cassandra unavailable
                        C--xM: unavailable
                        M-->>API: 503 dialog_result_unknown
                        API-->>A: Retry same request
                    end
                end
            end

            par Repair/write canonical dialog
                M->>C: UPSERT dialog_by_id<br/>{dialog_id, members, created_at}
            and Projection for user A
                M->>C: UPSERT dialogs_by_user(userA, dialog_id)
            and Projection for user B
                M->>C: UPSERT dialogs_by_user(userB, dialog_id)
            end

            alt New pair reserved and projections written
                rect rgb(232, 245, 233)
                    M-->>API: 201 {dialog_id}
                    API-->>A: 201 {dialog_id}
                end
            else Pair already existed
                rect rgb(255, 248, 225)
                    M-->>API: 200 existing {dialog_id}
                    API-->>A: 200 existing dialog
                end
            else Cassandra fails during projection writes
                rect rgb(255, 248, 225)
                    M-->>API: 503 projection_incomplete
                    API-->>A: Retry
                    Note over A,C: Retry reads the reserved dialog_id<br/>and idempotently repairs every projection.
                end
            end
        end
    end

    opt Service crashes after pair reservation
        rect rgb(255, 248, 225)
            Note over A,C: pair_key still points to the canonical dialog_id.<br/>Retry cannot create a second 1:1 dialog<br/>and completes missing projections.
        end
    end
```

### DLG-01 decisions

- Uniqueness is defined by canonical pair_key, not by a distributed lock.
- Cross-partition projections are repaired idempotently after partial failure.
- The synchronous Profile check exists only on dialog creation. Message sending
  does not depend on Profile Service.

---

## MSG-01. WebSocket command acceptance

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Connected Client
        actor A as Sender Client
    end
    box rgb(232, 245, 233) Realtime
        participant WS as WebSocket Gateway
    end
    box rgb(255, 243, 224) Coordination and Broker
        participant V as Valkey Rate Limiter
        participant K as Kafka messages.commands
    end

    A->>+WS: message.send.v1<br/>{request_id, client_message_id,<br/>dialog_id, text, attachment_ids}
    WS->>WS: Bind sender_id from connection<br/>Never trust sender_id from payload

    alt Unsupported frame version or malformed JSON
        rect rgb(255, 235, 238)
            WS-->>A: error {request_id, code=ws.invalid_frame}
            Note over A,WS: Frame never reaches Kafka.
        end
    else Payload exceeds size or attachment limits
        rect rgb(255, 235, 238)
            WS-->>A: error {code=message.payload_too_large}
        end
    else client_message_id is not UUIDv7
        rect rgb(255, 235, 238)
            WS-->>A: error {code=message.invalid_id}
        end
    else Syntactically valid
        WS->>+V: Consume per-user and per-connection quota
        alt Rate limit exceeded
            rect rgb(255, 235, 238)
                V-->>WS: REJECT + retry_after
                WS-->>A: error {code=rate_limited, retry_after}
            end
        else Rate limiter unavailable
            rect rgb(255, 235, 238)
                V--xWS: timeout
                WS-->>A: error {code=dependency_unavailable, retryable=true}
                Note over WS,K: Fail closed for message commands.<br/>Typing uses a different fail-open policy.
            end
        else Allowed
            V-->>-WS: ALLOW
            WS->>+K: Publish message.send.v1<br/>key=dialog_id<br/>sender_id from authenticated connection
            alt Broker ACK
                rect rgb(232, 245, 233)
                    K-->>WS: accepted offset
                    WS-->>A: command.accepted<br/>{request_id, client_message_id}
                    Note over A,K: accepted means queued,<br/>not yet persisted as SENT.
                end
            else Kafka unavailable or publish timeout
                rect rgb(255, 235, 238)
                    K--xWS: unavailable / timeout
                    WS-->>A: error {request_id,<br/>code=message.queue_unavailable,<br/>retryable=true}
                    Note over A,WS: Retry uses the same client_message_id.
                end
            end
        end
    end

    opt Socket drops after Kafka ACK but before command.accepted
        rect rgb(255, 248, 225)
            Note over A,K: Client retries after reconnect with the same ID.<br/>Kafka may receive a duplicate command.<br/>Messages Service deduplicates it.
        end
    end
```

### MSG-01 decisions

- WebSocket Gateway validates transport shape, not dialog membership.
- command.accepted confirms only durable Kafka acceptance.
- The client keeps the message in PENDING until message.persisted is received.

---

## MSG-02. Durable message processing and realtime fan-out

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Clients
        actor A as Sender Client
        actor B as Recipient Client
    end
    box rgb(255, 243, 224) Kafka
        participant KC as messages.commands
        participant KE as messages.events
        participant DLQ as messages.commands.dlq
    end
    box rgb(232, 245, 233) Messaging
        participant MW as Messages Worker
    end
    box rgb(243, 229, 245) Durable Storage
        participant C as Messages Cassandra
    end
    box rgb(232, 245, 233) Realtime
        participant D as WS Event Dispatcher
        participant WSA as Sender WS Node
        participant WSB as Recipient WS Node
    end
    box rgb(255, 243, 224) Routing
        participant V as Valkey Registry and PubSub
    end

    KC->>+MW: message.send.v1<br/>key=dialog_id
    MW->>MW: Validate version and contract

    alt Poison envelope or unsupported contract
        rect rgb(255, 235, 238)
            MW->>DLQ: Publish original envelope + safe error metadata
            DLQ-->>MW: broker ACK
            MW-->>KC: ACK command offset
            Note over KC,DLQ: Poison does not block the partition.
        end
    else Valid command
        MW->>+C: Read dialog_by_id at LOCAL_QUORUM
        alt Dialog missing or sender is not a member
            rect rgb(255, 235, 238)
                C-->>MW: missing / non-member
                MW->>KE: Publish message.rejected.v1<br/>target_user_id=sender<br/>client_message_id
                KE-->>MW: broker ACK
                MW-->>KC: ACK command offset
            end
        else Cassandra unavailable
            rect rgb(255, 235, 238)
                C--xMW: unavailable / timeout
                MW-->>KC: NACK / no offset commit
                Note over KC,C: Kafka redelivers with backoff.<br/>No rejection is sent for a transient failure.
            end
        else Sender is a member
            C-->>-MW: dialog + peer_user_id
            MW->>MW: Compute payload_hash<br/>prepare canonical message snapshot

            critical Idempotency reservation
                MW->>+C: LWT INSERT message_request_by_sender_bucket<br/>(sender_id, client_message_id,<br/>payload_hash, canonical snapshot) IF NOT EXISTS
                C-->>-MW: first reservation or existing snapshot
            option LWT timeout
                rect rgb(255, 248, 225)
                    C--xMW: WriteTimeout
                    MW->>C: SERIAL read by sender_id + client_message_id
                    alt Reservation exists
                        C-->>MW: canonical snapshot
                    else Reservation absent
                        C-->>MW: null
                        MW->>C: Bounded retry of identical LWT
                    else Result cannot be resolved now
                        C--xMW: unavailable
                        MW-->>KC: NACK
                    end
                end
            end

            alt Same client_message_id with different payload_hash
                rect rgb(255, 235, 238)
                    MW->>KE: Publish message.rejected.v1<br/>code=idempotency_payload_mismatch
                    KE-->>MW: broker ACK
                    MW-->>KC: ACK command offset
                end
            else First or safe duplicate command
                par Idempotent timeline projection
                    MW->>C: UPSERT messages_by_dialog_bucket<br/>message status=SENT
                and Sender inbox projection
                    MW->>C: UPSERT sync_events_by_user(sender)<br/>message.persisted
                and Recipient inbox projection
                    MW->>C: UPSERT sync_events_by_user(recipient)<br/>message.created
                and Dialog summary projections
                    MW->>C: UPSERT dialog summaries for both users
                end

                alt Every required projection confirmed
                    rect rgb(232, 245, 233)
                        MW->>+KE: Publish message.persisted.v1 for sender<br/>and message.created.v1 for recipient<br/>event_id deterministic per target
                        alt Kafka event ACK
                            KE-->>MW: accepted
                            MW-->>-KC: ACK command offset
                        else Kafka events unavailable
                            rect rgb(255, 248, 225)
                                KE--xMW: timeout / unavailable
                                MW-->>KC: NACK / no offset commit
                                Note over KC,C: Command redelivery loads the same<br/>idempotency snapshot, repairs projections,<br/>and republishes deterministic events.
                            end
                        end
                    end
                else Projection write failed
                    rect rgb(255, 248, 225)
                        C--xMW: partial success / timeout
                        MW-->>KC: NACK
                        Note over MW,C: Existing canonical snapshot allows<br/>idempotent projection repair on redelivery.
                    end
                end
            end
        end
    end

    par Sender realtime event
        KE->>+D: message.persisted.v1<br/>target_user_id=sender
        D->>+V: Resolve active gateway_ids(sender)
        alt Sender has active connections
            V-->>D: gateway_id list
            D->>V: PUBLISH gateway:{id}
            V-->>WSA: event
            WSA-->>A: message.persisted<br/>{message_id, client_message_id, SENT}
        else Sender offline
            rect rgb(255, 248, 225)
                V-->>D: empty
                Note over A,C: Durable sync projection remains available.
            end
        else Registry unavailable
            rect rgb(255, 248, 225)
                V--xD: timeout
                D-->>KE: NACK for bounded retry
            end
        end
        D-->>KE: ACK after routing attempt
    and Recipient realtime event
        KE->>+D: message.created.v1<br/>target_user_id=recipient
        D->>+V: Resolve active gateway_ids(recipient)
        alt Recipient online
            V-->>D: gateway_id list
            D->>V: PUBLISH gateway:{id}
            V-->>WSB: event
            WSB-->>B: message.created<br/>{message, status=SENT}
            Note over B,WSB: Push alone does not mark DELIVERED.<br/>Client must send an explicit receipt.
        else Recipient offline
            rect rgb(255, 248, 225)
                V-->>D: empty
                Note over B,C: Message stays SENT.<br/>Recipient obtains it through /sync.
            end
        end
        D-->>KE: ACK after routing attempt
    end

    opt Dispatcher or WS Node crashes after push but before ACK
        rect rgb(255, 248, 225)
            Note over A,KE: Kafka may redeliver the event.<br/>Client deduplicates by event_id and message_id.
        end
    end
```

### MSG-02 critical invariants

- The idempotency reservation stores the complete canonical snapshot required to
  repair every projection after a partial write.
- Event IDs are deterministic for message, event type and target user.
- A broker ACK without a client ACK never means DELIVERED.
- Valkey Pub/Sub is only a low-latency hint. Cassandra sync projection is the
  source for catch-up.

---

## RCPT-01. Delivered and read receipts

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Clients
        actor A as Sender Client
        actor B as Recipient Client
    end
    box rgb(232, 245, 233) Realtime
        participant WS as WebSocket Gateway
        participant D as WS Event Dispatcher
    end
    box rgb(255, 243, 224) Kafka
        participant KC as receipts.commands
        participant KE as messages.events
    end
    box rgb(232, 245, 233) Messaging
        participant MW as Messages Worker
    end
    box rgb(243, 229, 245) Durable Storage
        participant C as Messages Cassandra
    end

    B->>B: Persist/render message locally
    B->>+WS: message.delivered.v1<br/>{message_id, dialog_id}
    WS->>KC: Publish authenticated recipient_id
    KC-->>WS: broker ACK
    WS-->>-B: command.accepted
    KC->>+MW: delivered command
    MW->>+C: Read message receipt + dialog membership

    alt Caller is not the recipient/member
        rect rgb(255, 235, 238)
            C-->>MW: unauthorized
            MW->>KE: receipt.rejected.v1 to caller
            KE-->>MW: ACK
            MW-->>KC: ACK command offset
        end
    else Message does not exist
        rect rgb(255, 235, 238)
            C-->>MW: missing
            MW->>KE: receipt.rejected.v1<br/>code=message_not_found
            KE-->>MW: ACK
            MW-->>KC: ACK command offset
        end
    else Valid recipient
        MW->>C: LWT SET status_rank=max(current, DELIVERED)<br/>increment status_version only on advance
        alt Status advanced SENT to DELIVERED
            rect rgb(232, 245, 233)
                C-->>MW: APPLIED + status_version
                MW->>C: UPSERT sync event for sender
                MW->>KE: Publish message.status_changed.v1<br/>DELIVERED + status_version
                KE-->>MW: broker ACK
                MW-->>KC: ACK command offset
                KE->>D: status event target=sender
                D-->>A: message.status_changed DELIVERED
            end
        else Duplicate DELIVERED
            rect rgb(255, 248, 225)
                C-->>MW: NOT_APPLIED current=DELIVERED/READ
                MW->>KE: Publish receipt.confirmed.v1 to recipient<br/>current status
                KE-->>MW: broker ACK
                MW-->>KC: ACK command offset
            end
        else Cassandra unavailable
            rect rgb(255, 235, 238)
                C--xMW: unavailable
                MW-->>KC: NACK / redelivery
            end
        end
    end

    opt User opens the dialog and message becomes visible
        B->>WS: message.read.v1<br/>{dialog_id, through_message_id}
        WS->>KC: Publish authenticated reader_id
        KC-->>WS: broker ACK
        WS-->>B: command.accepted
        KC->>MW: read command
        MW->>C: Validate membership and cursor<br/>advance all eligible receipts to READ

        alt READ arrives before DELIVERED processing
            rect rgb(232, 245, 233)
                C-->>MW: Advance SENT directly to READ
                Note over MW,C: READ semantically includes delivery.<br/>A later DELIVERED command becomes a no-op.
            end
        else Already READ or duplicate range
            rect rgb(255, 248, 225)
                C-->>MW: no state change
            end
        else Invalid through_message_id
            rect rgb(255, 235, 238)
                C-->>MW: not in dialog / future cursor
                MW->>KE: receipt.rejected.v1
            end
        end

        MW->>C: UPSERT sender sync event if state advanced
        MW->>KE: Publish message.status_changed.v1 READ
        KE-->>MW: broker ACK
        MW-->>KC: ACK command offset
        KE->>D: READ event target=sender
        alt Sender online
            D-->>A: message.status_changed READ
        else Sender offline
            rect rgb(255, 248, 225)
                Note over A,C: Updated status is returned by /sync<br/>and message history later.
            end
        end
    end

    opt State committed but event publication fails
        rect rgb(255, 248, 225)
            Note over KC,C: Receipt command is redelivered.<br/>Monotonic update becomes a no-op,<br/>then the current status event is republished.
        end
    end
```

### RCPT-01 decisions

- Status transitions use numeric rank and version; backward transitions are
  impossible.
- A read range is preferable to one command per message.
- Duplicate ACKs return the current state and never create a second transition.

---

## TYP-01. Ephemeral typing status

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Clients
        actor A as Typing Client
        actor B as Peer Client
    end
    box rgb(232, 245, 233) Realtime
        participant WSA as Sender WS Node
        participant WSB as Peer WS Node
    end
    box rgb(232, 245, 233) Authorization
        participant M as Messages Service
    end
    box rgb(255, 243, 224) Ephemeral Coordination
        participant V as Valkey Membership Cache and PubSub
    end

    A->>+WSA: typing.started.v1<br/>{dialog_id}
    WSA->>WSA: Validate frame<br/>throttle by connection + dialog

    alt Event coalesced by throttle
        rect rgb(255, 248, 225)
            WSA-->>A: typing.accepted {coalesced=true}
            Note over A,WSA: Repeated keypresses do not create<br/>one network event per character.
        end
    else First event in throttle window
        WSA->>+V: GET membership cache(dialog_id, user_id)
        alt Positive cache hit
            V-->>WSA: member=true
        else Cache miss
            V-->>WSA: miss
            WSA->>+M: GET /internal/v1/dialogs/{id}/members/{user_id}
            alt User is a member
                M-->>WSA: 204
                WSA->>V: Cache positive membership with bounded TTL
            else User is not a member
                rect rgb(255, 235, 238)
                    M-->>WSA: 403
                    WSA-->>A: error typing.not_allowed
                end
            else Messages Service unavailable
                rect rgb(255, 248, 225)
                    M--xWSA: timeout
                    WSA-->>A: typing.dropped {retryable=false}
                    Note over WSA,M: Typing failure must not affect<br/>message send or connection health.
                end
            end
        else Negative cache hit
            rect rgb(255, 235, 238)
                V-->>WSA: member=false
                WSA-->>A: error typing.not_allowed
            end
        else Valkey unavailable
            rect rgb(255, 248, 225)
                V--xWSA: unavailable
                WSA-->>A: typing.dropped {retryable=false}
            end
        end

        opt Membership authorized
            WSA->>V: PUBLISH typing:{dialog_id}<br/>{user_id, state=STARTED, expires_at=now+5s}
            alt Peer has active connection
                V-->>WSB: typing event
                WSB-->>B: typing.changed STARTED + expires_at
                B->>B: Start local expiry timer
            else Peer offline
                rect rgb(255, 248, 225)
                    Note over B,V: Event is dropped. No replay.
                end
            end
            WSA-->>A: typing.accepted
        end
    end

    opt User stops typing explicitly
        A->>WSA: typing.stopped.v1 {dialog_id}
        WSA->>V: PUBLISH state=STOPPED
        V-->>WSB: typing event
        WSB-->>B: typing.changed STOPPED
        B->>B: Clear indicator
    end

    alt STOPPED event lost or sender disconnects
        rect rgb(255, 248, 225)
            Note over A,B: Peer UI clears indicator at expires_at.<br/>No durable cleanup process is required.
        end
    end
```

### TYP-01 decisions

- Typing is best-effort and explicitly fail-open relative to core messaging.
- Recipient UI expiration is authoritative; Redis keyspace expiry notifications
  are not required.
- Authorization is cached, but a cache miss never grants access.

---

## SYNC-01. Reconnect and catch-up without event loss

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Client and Edge
        actor C as Reconnecting Client
        participant API as API Gateway
    end
    box rgb(232, 245, 233) Realtime
        participant WS as WebSocket Gateway
    end
    box rgb(232, 245, 233) Messaging
        participant M as Messages Service
    end
    box rgb(243, 229, 245) Durable Storage
        participant DB as Messages Cassandra
    end

    Note over C,WS: Previous connection was lost.<br/>Client retains last durable sync_cursor.
    C->>+WS: Reconnect /ws with access cookie
    WS->>WS: Verify token and register connection

    alt Access token expired
        rect rgb(255, 235, 238)
            WS-->>C: close 4401
            C->>C: Run AUTH-03 refresh<br/>then reconnect
        end
    else Connected
        rect rgb(232, 245, 233)
            WS-->>-C: connection.ready
            C->>C: Buffer new realtime events<br/>until sync completes
        end

        loop While response has next_cursor
            C->>+API: GET /api/v1/sync?cursor=last_sync_cursor&limit=N
            API->>+M: Forward + access token
            M->>M: Verify JWT locally
            M->>+DB: Query sync_events_by_user bucket<br/>after cursor at LOCAL_QUORUM

            alt Page returned
                rect rgb(232, 245, 233)
                    DB-->>M: ordered events + next_cursor
                    M-->>API: 200 events + next_cursor
                    API-->>C: 200 page
                    C->>C: Merge by event_id/message_id/status_version<br/>persist new cursor only after local commit
                end
            else Cursor malformed or belongs to another user
                rect rgb(255, 235, 238)
                    DB-->>M: rejected
                    M-->>API: 400 sync.invalid_cursor
                    API-->>C: 400
                end
            else Cursor older than retained sync window
                rect rgb(255, 248, 225)
                    DB-->>M: outside retained buckets
                    M-->>API: 410 sync.full_resync_required
                    API-->>C: 410
                    C->>API: GET dialogs then paged histories
                end
            else Cassandra unavailable
                rect rgb(255, 235, 238)
                    DB--xM: unavailable / timeout
                    M-->>API: 503 message_store_unavailable
                    API-->>C: 503 + Retry-After
                    Note over C,DB: Keep old cursor and buffered WS events.<br/>Retry does not skip data.
                end
            end
        end

        par Realtime event arrives during HTTP sync
            WS-->>C: message.created or status.changed
            C->>C: Buffer event
        and HTTP catch-up finishes
            C->>C: Apply sync page transactionally
        end

        critical Merge boundary
            C->>C: Merge buffered events by deterministic IDs<br/>take greatest status_version<br/>advance cursor after local persistence
        option Client crashes during merge
            rect rgb(255, 248, 225)
                Note over C,DB: Old cursor is reused after restart.<br/>Duplicate sync events are safe.
            end
        end

        opt Newly received messages were persisted locally
            C->>WS: message.delivered.v1 range
            Note over C,WS: Delivery ACK happens after local durable handling,<br/>not merely after network receipt.
        end
    end
```

### SYNC-01 decisions

- Realtime delivery is an optimization; sync projection closes every gap.
- Client cursor advances only after the corresponding page is committed locally.
- Concurrent WebSocket events and HTTP catch-up are merged by deterministic IDs
  and monotonic status_version.

---

## AUTH-05. Current identity

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Client and Edge
        actor C as Client / Browser
        participant API as API Gateway
    end
    box rgb(232, 245, 233) Identity
        participant ID as Identity Service
    end
    box rgb(243, 229, 245) Durable Storage
        participant PG as Identity PostgreSQL
    end

    C->>+API: GET /api/v1/auth/me<br/>Cookie=access_token
    API->>+ID: Forward request
    ID->>ID: Verify RS256 locally<br/>iss, aud, exp, token_type

    alt JWT missing, invalid, or expired
        rect rgb(255, 235, 238)
            ID-->>API: 401 auth.invalid_token
            API-->>C: 401 + Cache-Control:no-store
        end
    else JWT valid
        ID->>+PG: SELECT credential identity BY sub
        alt User active
            rect rgb(232, 245, 233)
                PG-->>ID: user_id, email, role, status
                ID-->>API: 200 safe identity response
                API-->>C: 200 + Cache-Control:no-store
            end
        else User missing or disabled
            rect rgb(255, 235, 238)
                PG-->>ID: null / inactive
                ID-->>API: 401 auth.invalid_token
                API-->>C: 401 generic response
                Note over C,ID: Do not reveal whether a valid subject<br/>was deleted or disabled.
            end
        else PostgreSQL unavailable
            rect rgb(255, 235, 238)
                PG--xID: unavailable / timeout
                ID-->>API: 503 identity_store_unavailable
                API-->>C: 503 + Retry-After
            end
        end
    end
```

### AUTH-05 decision

Identity /me exposes credential-side fields only. Display name, bio, locale and
avatar are read from User Profile Service.

---

## DLG-02. List dialogs and read message history

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Client and Edge
        actor C as Client
        participant API as API Gateway
    end
    box rgb(232, 245, 233) Messaging
        participant M as Messages and Dialogues Service
    end
    box rgb(243, 229, 245) Durable Storage
        participant DB as Messages Cassandra
    end

    C->>+API: GET /api/v1/dialogs?cursor=&limit=
    API->>+M: Forward request
    M->>M: Verify JWT and decode opaque cursor

    alt Invalid token
        rect rgb(255, 235, 238)
            M-->>API: 401 auth.invalid_token
            API-->>C: 401
        end
    else Invalid cursor or limit
        rect rgb(255, 235, 238)
            M-->>API: 400 pagination.invalid_cursor
            API-->>C: 400
        end
    else Valid request
        M->>+DB: Query dialogs_by_user_bucket<br/>partition=user_id + bucket<br/>after clustering cursor
        alt Page found
            rect rgb(232, 245, 233)
                DB-->>M: dialog summaries + next_cursor
                M-->>API: 200 items + next_cursor
                API-->>C: 200 page
            end
        else Current bucket exhausted
            rect rgb(255, 248, 225)
                DB-->>M: empty + previous_bucket pointer
                M->>DB: Query previous non-empty bucket
                DB-->>M: items or end_of_list
                M-->>API: 200 page
                API-->>C: 200 page
            end
        else Cassandra unavailable
            rect rgb(255, 235, 238)
                DB--xM: unavailable / timeout
                M-->>API: 503 message_store_unavailable
                API-->>C: 503 + Retry-After
            end
        end
    end

    opt User opens one dialog
        C->>API: GET /api/v1/dialogs/{dialog_id}/messages<br/>?before=cursor&limit=N
        API->>M: Forward request
        M->>DB: Read dialog membership at LOCAL_QUORUM
        alt Caller is not a member
            rect rgb(255, 235, 238)
                DB-->>M: missing/non-member
                M-->>API: 404 dialog.not_found
                API-->>C: 404
                Note over C,M: 404 avoids revealing private dialog existence.
            end
        else Member
            DB-->>M: authorized + newest bucket
            loop Until page full or history exhausted
                M->>DB: Query messages_by_dialog_bucket<br/>before cursor
                DB-->>M: ordered rows
                opt Bucket exhausted before page is full
                    M->>DB: Continue in previous bucket
                    DB-->>M: older rows
                end
            end
            M-->>API: 200 messages + next_cursor
            API-->>C: 200 stable page
        else Cassandra unavailable
            rect rgb(255, 235, 238)
                DB--xM: unavailable / timeout
                M-->>API: 503 message_store_unavailable
                API-->>C: 503 + Retry-After
            end
        end
    end

    opt New message arrives while an older page is read
        rect rgb(255, 248, 225)
            Note over C,DB: Cursor is based on immutable message order,<br/>not page number. Newer inserts do not shift<br/>or duplicate the requested older page.
        end
    end
```

### DLG-02 decisions

- Every cursor is opaque, user-bound and contains the active time bucket plus
  clustering position.
- Private dialog lookup returns 404 to non-members.
- Page-number pagination is forbidden because concurrent messages make it
  unstable.

---

## OBJ-01. Request upload, direct PUT and finalize

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Client and Edge
        actor C as Client / Browser
        participant API as API Gateway
    end
    box rgb(232, 245, 233) Object Storage
        participant S as Object Storage Gateway Service
        participant CL as Pending Upload Cleanup Worker
    end
    box rgb(243, 229, 245) Durable Storage
        participant PG as Storage Metadata PostgreSQL
        participant O as MinIO
    end

    C->>+API: POST /api/v1/objects/uploads<br/>{purpose, filename, size, media_type, checksum}<br/>Idempotency-Key=K
    API->>+S: Forward request
    S->>S: Verify JWT locally<br/>validate purpose-specific limits

    alt Invalid size, media type, filename, or checksum
        rect rgb(255, 235, 238)
            S-->>API: 413 / 415 / 422
            API-->>C: validation error
        end
    else Valid upload intent
        S->>+PG: INSERT upload intent IF ABSENT<br/>{object_id, owner_id, object_key,<br/>expected metadata, status=PENDING}
        alt Same K + same payload
            rect rgb(255, 248, 225)
                PG-->>S: existing PENDING/READY object
            end
        else Same K + different payload
            rect rgb(255, 235, 238)
                PG-->>S: idempotency conflict
                S-->>API: 409 idempotency_payload_mismatch
                API-->>C: 409
            end
        else Metadata store unavailable
            rect rgb(255, 235, 238)
                PG--xS: unavailable
                S-->>API: 503 storage_metadata_unavailable
                API-->>C: 503 + Retry-After
            end
        else Intent created
            PG-->>-S: object_id + generated object_key
            S->>S: Generate short-lived presigned PUT<br/>signed size/type/checksum constraints
            S-->>-API: 201 {object_id, upload_url, expires_at}
            API-->>-C: 201 upload ticket
        end
    end

    C->>+O: PUT presigned URL<br/>binary + required headers
    alt Upload completed
        rect rgb(232, 245, 233)
            O-->>C: 200 / ETag
        end
    else URL expired
        rect rgb(255, 248, 225)
            O-->>C: 403 SignatureExpired
            C->>API: POST /uploads/{object_id}/renew
            API->>S: Renew request for same owner
            S->>PG: Verify PENDING and owner_id
            PG-->>S: valid
            S-->>API: new presigned PUT
            API-->>C: 200 new URL
        end
    else Network interruption or MinIO unavailable
        rect rgb(255, 248, 225)
            O--xC: timeout / partial upload
            Note over C,O: Client retries the same object key<br/>or renews the URL. PENDING is not READY.
        end
    end

    C->>+API: POST /api/v1/objects/{object_id}/finalize<br/>Idempotency-Key=F
    API->>+S: Forward finalize
    S->>+PG: SELECT object FOR UPDATE by object_id

    alt Foreign object
        rect rgb(255, 235, 238)
            PG-->>S: owner mismatch
            S-->>API: 404 object.not_found
            API-->>C: 404
        end
    else Object already READY
        rect rgb(255, 248, 225)
            PG-->>S: READY metadata
            S-->>API: 200 same object descriptor
            API-->>C: 200 idempotent result
        end
    else PENDING object
        PG-->>-S: expected metadata + object_key
        S->>+O: HEAD object
        alt Object missing or upload incomplete
            rect rgb(255, 248, 225)
                O-->>S: 404 / incomplete
                S-->>API: 409 upload.not_complete
                API-->>C: 409<br/>retry finalize later
            end
        else Size/checksum/type mismatch
            rect rgb(255, 235, 238)
                O-->>S: actual metadata
                S->>PG: UPDATE status=REJECTED + reason
                S-->>API: 422 upload.integrity_mismatch
                API-->>C: 422
                S->>O: Best-effort delete rejected object
            end
        else MinIO unavailable
            rect rgb(255, 235, 238)
                O--xS: unavailable / timeout
                S-->>API: 503 object_store_unavailable
                API-->>C: 503 + Retry-After
            end
        else Metadata matches
            rect rgb(232, 245, 233)
                O-->>-S: actual metadata
                S->>PG: UPDATE status=READY<br/>store trusted metadata
                PG-->>S: COMMIT
                S-->>API: 200 object descriptor
                API-->>C: 200 READY
            end
        end
    else Metadata PostgreSQL unavailable
        rect rgb(255, 235, 238)
            PG--xS: unavailable / timeout
            S-->>API: 503 storage_metadata_unavailable
            API-->>C: 503 + Retry-After
        end
    end

    opt Finalize response is lost after READY commit
        rect rgb(255, 248, 225)
            C->>API: Retry finalize with same F
            Note over C,PG: READY branch returns the same descriptor.<br/>No duplicate object is created.
        end
    end

    loop Periodic bounded cleanup
        CL->>PG: Claim expired PENDING/REJECTED records
        PG-->>CL: bounded batch
        CL->>O: Delete orphan object keys if present
        CL->>PG: Mark cleaned / delete metadata by policy
    end
```

### OBJ-01 decisions

- Application bytes do not pass through Object Storage Gateway.
- object_key is generated by the service and never selected by the client.
- A successful PUT is not sufficient; only finalized READY objects may be used.
- Antivirus and deep content inspection are post-MVP. Size, checksum, declared
  media type and purpose-specific allowlists are part of MVP.

---

## OBJ-02. Attach media to a message and download it

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Clients and Edge
        actor A as Sender Client
        actor B as Recipient Client
        participant API as API Gateway
    end
    box rgb(232, 245, 233) Realtime
        participant WS as WebSocket Gateway
    end
    box rgb(255, 243, 224) Kafka
        participant K as messages.commands
    end
    box rgb(232, 245, 233) Application Services
        participant M as Messages Service
        participant S as Object Storage Service
    end
    box rgb(243, 229, 245) Durable Storage
        participant C as Messages Cassandra
        participant PG as Storage Metadata PostgreSQL
        participant O as MinIO
    end

    Note over A,S: Sender has completed OBJ-01.<br/>Every attachment_id is READY.
    A->>+WS: message.send.v1<br/>{client_message_id, dialog_id,<br/>attachment_ids}
    WS->>+K: Publish authenticated command<br/>key=dialog_id
    K-->>-WS: broker ACK
    WS-->>-A: command.accepted
    K->>+M: command
    M->>C: Validate dialog membership
    C-->>M: sender is member

    loop For each attachment_id
        M->>+S: POST /internal/v1/objects/{id}/validate-use<br/>{owner_id=sender, purpose=MESSAGE}
        S->>+PG: Read trusted metadata
        alt READY and owned by sender
            rect rgb(232, 245, 233)
                PG-->>S: descriptor
                S-->>M: 200 immutable descriptor snapshot
            end
        else PENDING or REJECTED
            rect rgb(255, 235, 238)
                PG-->>S: non-ready status
                S-->>M: 409 object.not_ready
                M->>K: Publish message.rejected to sender<br/>ACK command
            end
        else Owner mismatch or object missing
            rect rgb(255, 235, 238)
                PG-->>S: mismatch / missing
                S-->>M: 404 object.not_found
                M->>K: Publish message.rejected<br/>ACK command
            end
        else Storage dependency unavailable
            rect rgb(255, 248, 225)
                PG--xS: timeout / unavailable
                S--xM: 503
                M-->>K: NACK command
                Note over K,S: Redelivery retries validation.<br/>No partial message is exposed.
            end
        end
    end

    opt All attachment descriptors validated
        rect rgb(232, 245, 233)
            M->>C: Run MSG-02 idempotency reservation<br/>store descriptor snapshots in message
            C-->>M: message persisted
            M->>K: Publish message events
            M-->>K: ACK command
        end
    end

    B->>+API: GET /api/v1/messages/{message_id}/attachments/{object_id}/download
    API->>+M: Forward + access token
    M->>C: Read message and dialog membership

    alt Caller is not a dialog member
        rect rgb(255, 235, 238)
            C-->>M: forbidden / hidden
            M-->>API: 404 attachment.not_found
            API-->>B: 404
        end
    else Object is not attached to this message
        rect rgb(255, 235, 238)
            C-->>M: message exists, object absent
            M-->>API: 404 attachment.not_found
            API-->>B: 404
        end
    else Authorized
        C-->>M: attachment descriptor
        M->>+S: POST /internal/v1/objects/{id}/download-ticket
        S->>PG: Verify object still readable
        alt Object READY
            rect rgb(232, 245, 233)
                PG-->>S: object_key
                S->>S: Generate short-lived presigned GET
                S-->>M: download_url + expires_at
                M-->>API: 200 download ticket
                API-->>B: 200 download ticket
                B->>+O: GET presigned URL
                O-->>-B: 200 bytes
            end
        else Object was administratively removed
            rect rgb(255, 235, 238)
                PG-->>S: DELETED/BLOCKED
                S-->>M: 410 object.gone
                M-->>API: 410 attachment.gone
                API-->>B: 410
            end
        else Storage or MinIO unavailable
            rect rgb(255, 235, 238)
                S--xM: 503
                M-->>API: 503 attachment_unavailable
                API-->>B: 503 + Retry-After
            end
        end
    end
```

### OBJ-02 decisions

- A message stores a trusted immutable attachment metadata snapshot, never a
  permanent public URL.
- Download authorization belongs to Messages Service because it owns dialog
  membership.
- Storage Service signs bytes only after receiving an internal authorization
  decision from the owning business service.

---

## AVT-01. Set or replace profile avatar

```mermaid
%%{init: {"theme":"base","themeVariables":{"actorBkg":"#E8F1FF","actorBorder":"#4C6FFF","signalColor":"#263238","noteBkgColor":"#FFF4CC","activationBkgColor":"#D7E4FF","sequenceNumberColor":"#FFFFFF"}}}%%
sequenceDiagram
    autonumber
    box rgb(227, 242, 253) Client and Edge
        actor C as Client
        participant API as API Gateway
    end
    box rgb(232, 245, 233) Application Services
        participant P as User Profile Service
        participant S as Object Storage Service
    end
    box rgb(243, 229, 245) Durable Storage
        participant PPG as Profile PostgreSQL
        participant SPG as Storage Metadata PostgreSQL
    end

    Note over C,S: Client has finalized an object with purpose=AVATAR.
    C->>+API: PATCH /api/v1/profiles/me/avatar<br/>{object_id}<br/>If-Match=profile_version
    API->>+P: Forward request
    P->>P: Verify JWT locally<br/>extract owner_id

    alt Invalid token
        rect rgb(255, 235, 238)
            P-->>API: 401 auth.invalid_token
            API-->>C: 401
        end
    else Token valid
        P->>+S: POST /internal/v1/objects/{id}/validate-use<br/>{owner_id, purpose=AVATAR}
        S->>+SPG: Read trusted metadata

        alt Object missing or owned by another user
            rect rgb(255, 235, 238)
                SPG-->>S: missing / owner mismatch
                S-->>P: 404 object.not_found
                P-->>API: 404 avatar.not_found
                API-->>C: 404
            end
        else Object PENDING or REJECTED
            rect rgb(255, 235, 238)
                SPG-->>S: non-ready
                S-->>P: 409 object.not_ready
                P-->>API: 409 avatar.not_ready
                API-->>C: 409
            end
        else Wrong MIME, size, or image dimensions
            rect rgb(255, 235, 238)
                SPG-->>S: READY but invalid for AVATAR
                S-->>P: 422 avatar.invalid_media
                P-->>API: 422
                API-->>C: 422
            end
        else Storage unavailable
            rect rgb(255, 235, 238)
                SPG--xS: unavailable
                S--xP: 503
                P-->>API: 503 avatar_validation_unavailable
                API-->>C: 503 + Retry-After
            end
        else Valid avatar object
            rect rgb(232, 245, 233)
                SPG-->>S: immutable descriptor
                S-->>-P: 200 descriptor
                P->>+PPG: UPDATE profile<br/>SET avatar_object_id, version=version+1<br/>WHERE user_id=sub AND version=If-Match
                alt Profile updated
                    PPG-->>P: updated profile + previous_avatar_id
                    P-->>API: 200 profile + new ETag
                    API-->>C: 200
                else Version conflict
                    rect rgb(255, 248, 225)
                        PPG-->>P: zero rows + current version
                        P-->>API: 409 profile.version_conflict
                        API-->>C: Reload profile and retry
                    end
                else Profile PostgreSQL unavailable
                    rect rgb(255, 235, 238)
                        PPG--xP: unavailable / timeout
                        P-->>API: 503 profile_store_unavailable
                        API-->>C: 503 + Retry-After
                    end
                end
            end
        end
    end

    opt Response is lost after profile update
        rect rgb(255, 248, 225)
            C->>API: GET /api/v1/profiles/me
            Note over C,PPG: Client reconciles current avatar and version.<br/>Repeating the same object assignment is safe.
        end
    end

    opt Previous avatar became unreferenced
        rect rgb(255, 248, 225)
            Note over P,S: Do not synchronously delete it.<br/>A separate bounded cleanup policy removes<br/>unreferenced objects after a grace period.
        end
    end
```

### AVT-01 decisions

- Profile Service owns the avatar reference; Storage Service owns the object.
- Replacing an avatar never performs object deletion inside the profile
  transaction.
- The same optimistic profile version protects text fields and avatar changes.

---

## 4. Client retry contract

| Situation | Client behavior |
|---|---|
| 400, 404, 409 payload mismatch, 413, 415, 422 | Do not retry unchanged request |
| 401 access token expired | Run refresh once, then repeat the original operation |
| 401 refresh invalid/reused | Clear local auth state and require login |
| 423 refresh in progress | Retry same refresh token and same Idempotency-Key after Retry-After |
| 429 rate limited | Retry after server delay with the same client_message_id |
| 503 before command.accepted | Retry with backoff and the same operation ID |
| command.accepted but no message.persisted | Keep message PENDING; reconnect and call /sync; retry same client_message_id if unresolved |
| WebSocket disconnect | Reconnect with jitter, call /sync from last committed cursor |
| Upload PUT interrupted | Retry same object ticket or renew it; do not create another object ID |
| Finalize response lost | Repeat finalize with the same object ID and Idempotency-Key |

## 5. Server-side failure contract

| Boundary | Durable fence | Retry behavior |
|---|---|---|
| Identity registration -> Kafka | PostgreSQL transactional outbox | Relay retries; Profile consumer deduplicates event_id |
| Refresh rotation | Cassandra LWT + recoverable rotation result | Same Idempotency-Key returns same token pair |
| WS command -> Kafka | Kafka broker ACK | No command.accepted before ACK |
| Kafka command -> Cassandra | Canonical idempotency snapshot | Redelivery repairs projections |
| Cassandra -> Kafka event | Command offset remains uncommitted | Redelivery republishes deterministic event_id |
| Kafka event -> WebSocket | Client dedupe + Cassandra /sync | Duplicate push is safe; missed push is caught up |
| Receipt update | Monotonic status_rank + status_version | Duplicate/out-of-order ACK cannot move state backward |
| Media upload | Metadata state PENDING -> READY | Finalize is idempotent |

## 6. Explicitly deferred diagrams

The following flows are outside MVP and intentionally have no sequence diagrams:

- group chat membership changes;
- mobile push through APNs/FCM;
- edit/delete message;
- reactions, replies and forwarding;
- user presence history;
- moderation, antivirus and transcoding;
- CDN cache invalidation;
- multi-region failover;
- SSD to HDD migration;
- end-to-end encryption and key exchange.
