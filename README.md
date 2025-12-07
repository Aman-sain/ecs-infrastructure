# ECS Infrastructure Repository

This repository manages all AWS infrastructure for the ECS auto-deploy system.

## 🏗️ Infrastructure Components

- VPC with public/private subnets (3 AZs)
- NAT Gateway
- Application Load Balancer with SSL
- ECS Fargate Cluster
- ECR Repositories
- IAM Roles
- CloudWatch Log Groups
- Security Groups

## 📋 Prerequisites

- AWS CLI configured
- Python 3.9+
- boto3, pyyaml installed
- Terraform state stored in S3

## 🚀 Deployment

### Manual Deployment
```bash
python3 deploy-infra.py
```

### Via Jenkins
Just push changes to `main` branch - Jenkins will deploy automatically.

## 📝 What Gets Created

- **VPC**: 10.100.0.0/16
- **ECS Cluster**: auto-deploy-prod-cluster
- **ECR Repos**: auto-deploy-backend, auto-deploy-frontend
- **IAM Roles**: Execution and Task roles
- **S3 Backend**: terraform-state-ecs-autodeploy-{account-id}
- **DynamoDB**: terraform-state-lock

## 🔧 Infrastructure as Code

All infrastructure is managed via Python scripts using boto3 (no Terraform needed).

## 📊 Cost Estimate

~$85/month:
- NAT Gateway: $32
- ALB: $20
- ECS Fargate: $30
- Other: $3

## 🔄 CI/CD

Jenkins pipeline automatically:
1. Validates infrastructure code
2. Creates/updates all AWS resources
3. Outputs resource IDs for service deployments
4. Sends email notifications

## 📂 Structure

```
infrastructure/
├── deploy-infra.py          # Main deployment script
├── Jenkinsfile             # Jenkins pipeline
├── config/
│   └── infrastructure.yaml # Infrastructure config
├── scripts/
│   ├── cleanup.py         # Cleanup old resources
│   └── validate.py        # Validate infrastructure
└── README.md
```

## 🎯 Usage

**One-time setup:**
```bash
# Deploy infrastructure
python3 deploy-infra.py

# Save outputs
./scripts/save-outputs.sh
```

**Updates:**
```bash
git add .
git commit -m "Update infrastructure"
git push origin main
# Jenkins deploys automatically
```

## 🔐 Security

- All secrets in SSM Parameter Store
- IAM roles with least privilege
- VPC endpoints for AWS services
- Private subnets for ECS tasks
- Security groups with minimal access

## 📞 Support

Check CloudFormation/boto3 outputs:
```bash
python3 deploy-infra.py --dry-run
```

---

**Maintained by DevOps Team**
