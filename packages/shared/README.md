# Shared Python utilities

Both applications install their own authentication endpoints using `chatflow_shared.auth.install_auth` with their own SQLAlchemy engine and cookie name. Each application owns the database schema and authorization checks for its resources. Shared code may depend on framework libraries and contains no imports from either application.
