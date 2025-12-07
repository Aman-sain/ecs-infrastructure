# ECS Infrastructure with Pulumi

State stored in S3: `s3://terraform-state-ecs-autodeploy-724772079986/pulumi`

## Benefits
- Automatic resource detection
- State locking in S3
- Handles AWS limits gracefully
- Idempotent deployments
- Python-based IaC

## Deploy
Jenkins automatically runs Pulumi to deploy all infrastructure.

See Jenkinsfile for details.
