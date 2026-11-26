# Deployment entry points

The root Compose file can launch either application or both. [Messenger](../apps/messenger/README.md) uses Nginx and Redis on its own Compose network. The proxy configuration and disposable fault test live in [services/messenger](messenger/). [AI Chat](../apps/ai-chat/README.md) runs its own API and PostgreSQL. Existing external deployments are managed separately.
