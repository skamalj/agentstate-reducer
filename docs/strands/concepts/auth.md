# Authentication

Neither provider invents its own authentication. Each defers entirely to the native SDK's full auth surface — **boto3** for DynamoDB, **pymongo** for MongoDB. In both cases you have two paths:

1. **The standard mechanism** — the boto3 credential chain, or a MongoDB connection URI.
2. **Inject a pre-built client/session** — hand the provider a fully configured `boto3.Session` or `pymongo.MongoClient` and it uses that as-is.

The common cases need only a string or a single parameter; anything advanced is reachable by building the client yourself.

## DynamoDB (via boto3)

The [DynamoDB provider](../providers/dynamodb.md) resolves credentials through boto3's standard credential chain, or through a `boto_session` you pass in.

| Auth type | How to configure |
|---|---|
| Env vars | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` — automatic |
| Named profile | `~/.aws/credentials` via `AWS_PROFILE` env var or `boto_session=boto3.Session(profile_name=...)` |
| AWS SSO / IAM Identity Center | Configured profile, then via profile or `boto_session` |
| IAM roles | EC2 instance profile, ECS task role, Lambda role — automatic in those environments |
| AssumeRole / web identity | Via profile config or a passed `boto_session` |
| DynamoDB Local / LocalStack | `endpoint_url="http://localhost:8000"` |

=== "Env vars (automatic)"

    ```python
    # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN in the environment
    from strands_session_dynamodb import DynamoDBSessionManager

    sm = DynamoDBSessionManager(
        session_id="user-123",
        table_name="strands-sessions",
        region_name="us-east-1",
    )
    ```

=== "Named profile / SSO"

    ```python
    import boto3
    from strands_session_dynamodb import DynamoDBSessionManager

    sm = DynamoDBSessionManager(
        session_id="user-123",
        table_name="strands-sessions",
        boto_session=boto3.Session(profile_name="my-sso-profile"),
    )
    ```

=== "DynamoDB Local"

    ```python
    from strands_session_dynamodb import DynamoDBSessionManager

    sm = DynamoDBSessionManager(
        session_id="user-123",
        table_name="strands-sessions",
        endpoint_url="http://localhost:8000",
        region_name="us-east-1",
    )
    ```

!!! note "No direct access_key / secret parameters — by design"
    Following AWS best practice, the provider exposes **no** raw `access_key` / `secret_key` constructor parameters. Raw keys go through env vars or a `boto_session` you construct yourself. This keeps long-lived secrets out of application code and steers you toward roles and profiles.

## MongoDB (via pymongo)

The [MongoDB provider](../providers/mongodb.md) resolves credentials through the MongoDB URI, or through a `pymongo.MongoClient` you pass in. Nearly every mechanism is expressible as URI options.

| Auth type | How to configure |
|---|---|
| No auth (local dev) | `mongodb://127.0.0.1:27017/` |
| Username / password (SCRAM) | `mongodb://user:pass@host/db` |
| TLS / SSL | URI options — `?tls=true` |
| Atlas (SRV + SCRAM) | `mongodb+srv://user:pass@cluster.mongodb.net/` |
| X.509 certificates | URI options + `client=MongoClient(..., tlsCertificateKeyFile=...)` |
| AWS IAM (`MONGODB-AWS`) | `?authMechanism=MONGODB-AWS` |
| LDAP / Kerberos (enterprise) | URI `authMechanism` or a custom `MongoClient` |

=== "Local / no auth"

    ```python
    from strands_session_mongodb import MongoDBSessionManager

    sm = MongoDBSessionManager(
        session_id="user-123",
        connection_string="mongodb://127.0.0.1:27017/",
    )
    ```

=== "Atlas (SRV + SCRAM)"

    ```python
    from strands_session_mongodb import MongoDBSessionManager

    sm = MongoDBSessionManager(
        session_id="user-123",
        connection_string="mongodb+srv://user:pass@cluster.mongodb.net/",
    )
    ```

=== "X.509 (pre-built client)"

    ```python
    from pymongo import MongoClient
    from strands_session_mongodb import MongoDBSessionManager

    client = MongoClient(
        "mongodb://host/db?tls=true&authMechanism=MONGODB-X509",
        tlsCertificateKeyFile="/path/to/client.pem",
    )
    sm = MongoDBSessionManager(session_id="user-123", client=client)
    ```

## Shared philosophy

Both providers follow the same rule:

!!! tip "Common cases in one line; anything advanced via a pre-built client"
    The everyday path — env-var credentials or a simple connection string — needs just one string or parameter. When you need more (assumed roles, SSO, X.509, IAM, Kerberos, custom timeouts or pools), build a `boto3.Session` or `pymongo.MongoClient` yourself and inject it. That single escape hatch exposes the **entire** auth capability of the underlying SDK, with nothing lost in translation.

## See also

- [DynamoDB Provider](../providers/dynamodb.md)
- [MongoDB Provider](../providers/mongodb.md)
- [What You Get](../core/index.md)
- [Build Your Own Backend](../core/building-a-backend.md)
