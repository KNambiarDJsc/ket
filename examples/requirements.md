# Example App — Requirements

- Members cannot delete projects.
- Only an owner may delete a project.
- Project creation must return within 2 seconds.
- A newly created project must appear in GET /projects immediately after creation.
- Deleting a project that does not exist must return a 404, not a 500.
- The service must expose a health check at GET /.
