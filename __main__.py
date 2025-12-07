"""
ECS Auto-Deploy Infrastructure with Pulumi
Handles existing resources automatically with state management in S3
"""
import pulumi
import pulumi_aws as aws
import json

# Configuration
config = pulumi.Config()
project_name = "auto-deploy"
environment = "prod"
region = "us-east-1"

# ============================================================================
# VPC Discovery - Use existing VPC (handles AWS limits gracefully)
# ============================================================================

def get_vpc_id():
    """Find existing VPC - tries multiple methods like Terraform would"""

    # Method 1: Try to find VPC by our tag
    try:
        vpcs = aws.ec2.get_vpcs(
            filters=[{"name": "tag:Name", "values": [f"{project_name}-{environment}-vpc"]}]
        )
        if vpcs.ids and len(vpcs.ids) > 0:
            pulumi.log.info(f"✓ Found VPC by tag: {vpcs.ids[0]}")
            return vpcs.ids[0]
    except:
        pass

    # Method 2: Try CIDR block (our standard CIDR)
    try:
        vpcs = aws.ec2.get_vpcs(
            filters=[{"name": "cidr-block", "values": ["10.100.0.0/16"]}]
        )
        if vpcs.ids and len(vpcs.ids) > 0:
            pulumi.log.info(f"✓ Found VPC by CIDR 10.100.0.0/16: {vpcs.ids[0]}")
            return vpcs.ids[0]
    except:
        pass

    # Method 3: Try default VPC
    try:
        vpcs = aws.ec2.get_vpcs(
            filters=[{"name": "isDefault", "values": ["true"]}]
        )
        if vpcs.ids and len(vpcs.ids) > 0:
            pulumi.log.info(f"✓ Using default VPC: {vpcs.ids[0]}")
            return vpcs.ids[0]
    except:
        pass

    # Method 4: Get any available VPC
    try:
        vpcs = aws.ec2.get_vpcs()
        if vpcs.ids and len(vpcs.ids) > 0:
            pulumi.log.info(f"✓ Using first available VPC: {vpcs.ids[0]}")
            return vpcs.ids[0]
    except:
        pass

    raise Exception("❌ No VPC found! Please create a VPC first.")

# Get VPC
vpc_id = get_vpc_id()
vpc = aws.ec2.Vpc.get("vpc", vpc_id)
pulumi.export("vpc_id", vpc.id)

# Get VPC subnets
subnets = aws.ec2.get_subnets(
    filters=[{"name": "vpc-id", "values": [vpc.id]}]
)

if not subnets.ids or len(subnets.ids) < 2:
    raise Exception(f"❌ VPC {vpc_id} needs at least 2 subnets for ALB. Found: {len(subnets.ids) if subnets.ids else 0}")

pulumi.log.info(f"✓ Found {len(subnets.ids)} subnets in VPC")

# ============================================================================
# Security Groups
# ============================================================================

# Security Group for ALB
alb_sg = aws.ec2.SecurityGroup(
    f"{project_name}-{environment}-alb-sg",
    name=f"{project_name}-{environment}-alb-sg",
    description="Security group for Application Load Balancer",
    vpc_id=vpc.id,
    ingress=[
        {
            "protocol": "tcp",
            "from_port": 80,
            "to_port": 80,
            "cidr_blocks": ["0.0.0.0/0"],
            "description": "HTTP from anywhere"
        },
        {
            "protocol": "tcp",
            "from_port": 443,
            "to_port": 443,
            "cidr_blocks": ["0.0.0.0/0"],
            "description": "HTTPS from anywhere"
        }
    ],
    egress=[{
        "protocol": "-1",
        "from_port": 0,
        "to_port": 0,
        "cidr_blocks": ["0.0.0.0/0"],
        "description": "Allow all outbound"
    }],
    tags={
        "Name": f"{project_name}-{environment}-alb-sg",
        "Environment": environment,
        "ManagedBy": "Pulumi"
    }
)

# Security Group for ECS Tasks
ecs_sg = aws.ec2.SecurityGroup(
    f"{project_name}-{environment}-ecs-sg",
    name=f"{project_name}-{environment}-ecs-sg",
    description="Security group for ECS tasks",
    vpc_id=vpc.id,
    ingress=[{
        "protocol": "tcp",
        "from_port": 0,
        "to_port": 65535,
        "security_groups": [alb_sg.id],
        "description": "Allow all traffic from ALB"
    }],
    egress=[{
        "protocol": "-1",
        "from_port": 0,
        "to_port": 0,
        "cidr_blocks": ["0.0.0.0/0"],
        "description": "Allow all outbound"
    }],
    tags={
        "Name": f"{project_name}-{environment}-ecs-sg",
        "Environment": environment,
        "ManagedBy": "Pulumi"
    }
)

# ============================================================================
# ECS Cluster
# ============================================================================

cluster = aws.ecs.Cluster(
    f"{project_name}-{environment}-cluster",
    name=f"{project_name}-{environment}-cluster",
    settings=[{
        "name": "containerInsights",
        "value": "enabled"
    }],
    tags={
        "Name": f"{project_name}-{environment}-cluster",
        "Environment": environment,
        "ManagedBy": "Pulumi"
    }
)

# Cluster Capacity Providers (Fargate)
cluster_capacity_providers = aws.ecs.ClusterCapacityProviders(
    f"{project_name}-cluster-capacity",
    cluster_name=cluster.name,
    capacity_providers=["FARGATE", "FARGATE_SPOT"],
    default_capacity_provider_strategies=[{
        "capacity_provider": "FARGATE",
        "weight": 1,
        "base": 1
    }]
)

# ============================================================================
# ECR Repositories
# ============================================================================

backend_repo = aws.ecr.Repository(
    f"{project_name}-backend",
    name=f"{project_name}-backend",
    image_scanning_configuration={
        "scan_on_push": True
    },
    image_tag_mutability="MUTABLE",
    tags={
        "Name": f"{project_name}-backend",
        "Environment": environment,
        "ManagedBy": "Pulumi"
    }
)

# Lifecycle policy for backend repo (keep last 10 images)
backend_lifecycle = aws.ecr.LifecyclePolicy(
    f"{project_name}-backend-lifecycle",
    repository=backend_repo.name,
    policy=json.dumps({
        "rules": [{
            "rulePriority": 1,
            "description": "Keep last 10 images",
            "selection": {
                "tagStatus": "any",
                "countType": "imageCountMoreThan",
                "countNumber": 10
            },
            "action": {
                "type": "expire"
            }
        }]
    })
)

frontend_repo = aws.ecr.Repository(
    f"{project_name}-frontend",
    name=f"{project_name}-frontend",
    image_scanning_configuration={
        "scan_on_push": True
    },
    image_tag_mutability="MUTABLE",
    tags={
        "Name": f"{project_name}-frontend",
        "Environment": environment,
        "ManagedBy": "Pulumi"
    }
)

# Lifecycle policy for frontend repo
frontend_lifecycle = aws.ecr.LifecyclePolicy(
    f"{project_name}-frontend-lifecycle",
    repository=frontend_repo.name,
    policy=json.dumps({
        "rules": [{
            "rulePriority": 1,
            "description": "Keep last 10 images",
            "selection": {
                "tagStatus": "any",
                "countType": "imageCountMoreThan",
                "countNumber": 10
            },
            "action": {
                "type": "expire"
            }
        }]
    })
)

# ============================================================================
# IAM Roles
# ============================================================================

# ECS Task Execution Role (for pulling images, writing logs)
task_execution_role = aws.iam.Role(
    f"{project_name}-ecs-execution-role",
    name=f"{project_name}-ecs-execution-role",
    assume_role_policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }),
    tags={
        "Name": f"{project_name}-ecs-execution-role",
        "Environment": environment,
        "ManagedBy": "Pulumi"
    }
)

# Attach policies to execution role
execution_role_policies = [
    aws.iam.RolePolicyAttachment(
        f"{project_name}-ecs-execution-policy",
        role=task_execution_role.name,
        policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
    ),
    aws.iam.RolePolicyAttachment(
        f"{project_name}-ecr-read-policy",
        role=task_execution_role.name,
        policy_arn="arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
    )
]

# ECS Task Role (for application permissions - SSM, DynamoDB, etc)
task_role = aws.iam.Role(
    f"{project_name}-ecs-task-role",
    name=f"{project_name}-ecs-task-role",
    assume_role_policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }),
    tags={
        "Name": f"{project_name}-ecs-task-role",
        "Environment": environment,
        "ManagedBy": "Pulumi"
    }
)

# Attach SSM policy to task role (for reading secrets)
task_role_ssm = aws.iam.RolePolicyAttachment(
    f"{project_name}-task-ssm-policy",
    role=task_role.name,
    policy_arn="arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess"
)

# ============================================================================
# CloudWatch Logs
# ============================================================================

log_group = aws.cloudwatch.LogGroup(
    f"/ecs/{project_name}-{environment}",
    name=f"/ecs/{project_name}-{environment}",
    retention_in_days=7,
    tags={
        "Name": f"{project_name}-logs",
        "Environment": environment,
        "ManagedBy": "Pulumi"
    }
)

# ============================================================================
# Application Load Balancer
# ============================================================================

alb = aws.lb.LoadBalancer(
    f"{project_name}-{environment}-alb",
    name=f"{project_name}-{environment}-alb",
    internal=False,
    load_balancer_type="application",
    security_groups=[alb_sg.id],
    subnets=subnets.ids,
    enable_deletion_protection=False,
    enable_http2=True,
    enable_cross_zone_load_balancing=True,
    tags={
        "Name": f"{project_name}-{environment}-alb",
        "Environment": environment,
        "ManagedBy": "Pulumi"
    }
)

# Default Target Group (for health checks)
default_tg = aws.lb.TargetGroup(
    f"{project_name}-default-tg",
    name=f"{project_name}-default-tg",
    port=80,
    protocol="HTTP",
    vpc_id=vpc.id,
    target_type="ip",
    deregistration_delay=30,
    health_check={
        "enabled": True,
        "path": "/",
        "protocol": "HTTP",
        "matcher": "200-499",
        "interval": 30,
        "timeout": 5,
        "healthy_threshold": 2,
        "unhealthy_threshold": 3
    },
    tags={
        "Name": f"{project_name}-default-tg",
        "Environment": environment,
        "ManagedBy": "Pulumi"
    }
)

# HTTP Listener (port 80)
http_listener = aws.lb.Listener(
    f"{project_name}-http-listener",
    load_balancer_arn=alb.arn,
    port=80,
    protocol="HTTP",
    default_actions=[{
        "type": "forward",
        "target_group_arn": default_tg.arn
    }],
    tags={
        "Name": f"{project_name}-http-listener",
        "Environment": environment,
        "ManagedBy": "Pulumi"
    }
)

# ============================================================================
# Outputs (used by service deployment pipelines)
# ============================================================================

pulumi.export("cluster_name", cluster.name)
pulumi.export("cluster_arn", cluster.arn)
pulumi.export("backend_repo_url", backend_repo.repository_url)
pulumi.export("frontend_repo_url", frontend_repo.repository_url)
pulumi.export("backend_repo_name", backend_repo.name)
pulumi.export("frontend_repo_name", frontend_repo.name)
pulumi.export("task_execution_role_arn", task_execution_role.arn)
pulumi.export("task_role_arn", task_role.arn)
pulumi.export("alb_dns_name", alb.dns_name)
pulumi.export("alb_arn", alb.arn)
pulumi.export("alb_zone_id", alb.zone_id)
pulumi.export("http_listener_arn", http_listener.arn)
pulumi.export("alb_security_group_id", alb_sg.id)
pulumi.export("ecs_security_group_id", ecs_sg.id)
pulumi.export("log_group_name", log_group.name)
pulumi.export("subnet_ids", json.dumps(subnets.ids))

# Summary
pulumi.log.info("=" * 60)
pulumi.log.info("✅ ECS Auto-Deploy Infrastructure")
pulumi.log.info("=" * 60)
pulumi.log.info(f"Cluster: {project_name}-{environment}-cluster")
pulumi.log.info(f"Region: {region}")
pulumi.log.info(f"VPC: {vpc_id}")
pulumi.log.info(f"Subnets: {len(subnets.ids)}")
pulumi.log.info("=" * 60)
