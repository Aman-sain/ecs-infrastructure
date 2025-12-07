"""
ECS Auto-Deploy Infrastructure with Pulumi
Handles existing resources automatically - imports if exists, creates if not
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
# Helper: Get or Create Resource Pattern
# ============================================================================

def try_get_security_group(name, vpc_id):
    """Try to get existing security group"""
    try:
        sgs = aws.ec2.get_security_groups(
            filters=[
                {"name": "group-name", "values": [name]},
                {"name": "vpc-id", "values": [vpc_id]}
            ]
        )
        if sgs.ids and len(sgs.ids) > 0:
            pulumi.log.info(f"✓ Found existing security group: {name}")
            return sgs.ids[0]
    except:
        pass
    return None

def try_get_ecs_cluster(name):
    """Try to get existing ECS cluster"""
    try:
        cluster = aws.ecs.get_cluster(cluster_name=name)
        if cluster.arn:
            pulumi.log.info(f"✓ Found existing ECS cluster: {name}")
            return cluster.arn
    except:
        pass
    return None

def try_get_ecr_repo(name):
    """Try to get existing ECR repository"""
    try:
        repo = aws.ecr.get_repository(name=name)
        if repo.arn:
            pulumi.log.info(f"✓ Found existing ECR repo: {name}")
            return repo
    except:
        pass
    return None

def try_get_iam_role(name):
    """Try to get existing IAM role"""
    try:
        role = aws.iam.get_role(name=name)
        if role.arn:
            pulumi.log.info(f"✓ Found existing IAM role: {name}")
            return role
    except:
        pass
    return None

def try_get_log_group(name):
    """Try to get existing CloudWatch log group"""
    try:
        lg = aws.cloudwatch.get_log_group(name=name)
        if lg.arn:
            pulumi.log.info(f"✓ Found existing log group: {name}")
            return lg
    except:
        pass
    return None

# ============================================================================
# Security Groups (get or create)
# ============================================================================

alb_sg_id = try_get_security_group(f"{project_name}-{environment}-alb-sg", vpc.id)
if alb_sg_id:
    alb_sg = aws.ec2.SecurityGroup.get(f"{project_name}-{environment}-alb-sg", alb_sg_id)
else:
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

ecs_sg_id = try_get_security_group(f"{project_name}-{environment}-ecs-sg", vpc.id)
if ecs_sg_id:
    ecs_sg = aws.ec2.SecurityGroup.get(f"{project_name}-{environment}-ecs-sg", ecs_sg_id)
else:
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
# ECS Cluster (get or create)
# ============================================================================

cluster_arn = try_get_ecs_cluster(f"{project_name}-{environment}-cluster")
if cluster_arn:
    cluster = aws.ecs.Cluster.get(f"{project_name}-{environment}-cluster", cluster_arn)
else:
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

# ============================================================================
# ECR Repositories (get or create)
# ============================================================================

backend_repo_data = try_get_ecr_repo(f"{project_name}-backend")
if backend_repo_data:
    backend_repo = aws.ecr.Repository.get(f"{project_name}-backend", backend_repo_data.name)
else:
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

frontend_repo_data = try_get_ecr_repo(f"{project_name}-frontend")
if frontend_repo_data:
    frontend_repo = aws.ecr.Repository.get(f"{project_name}-frontend", frontend_repo_data.name)
else:
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

# ============================================================================
# IAM Roles (get or create)
# ============================================================================

task_execution_role_data = try_get_iam_role(f"{project_name}-ecs-execution-role")
if task_execution_role_data:
    task_execution_role = aws.iam.Role.get(f"{project_name}-ecs-execution-role", task_execution_role_data.name)
else:
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

    # Attach policies
    aws.iam.RolePolicyAttachment(
        f"{project_name}-ecs-execution-policy",
        role=task_execution_role.name,
        policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
    )
    aws.iam.RolePolicyAttachment(
        f"{project_name}-ecr-read-policy",
        role=task_execution_role.name,
        policy_arn="arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
    )

task_role_data = try_get_iam_role(f"{project_name}-ecs-task-role")
if task_role_data:
    task_role = aws.iam.Role.get(f"{project_name}-ecs-task-role", task_role_data.name)
else:
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

    # Attach SSM policy
    aws.iam.RolePolicyAttachment(
        f"{project_name}-task-ssm-policy",
        role=task_role.name,
        policy_arn="arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess"
    )

# ============================================================================
# CloudWatch Logs (get or create)
# ============================================================================

log_group_data = try_get_log_group(f"/ecs/{project_name}-{environment}")
if log_group_data:
    log_group = aws.cloudwatch.LogGroup.get(f"/ecs/{project_name}-{environment}", log_group_data.name)
else:
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
# Application Load Balancer (always create new or get existing)
# ============================================================================

# Try to find existing ALB
try:
    albs = aws.lb.get_load_balancer(name=f"{project_name}-{environment}-alb")
    alb = aws.lb.LoadBalancer.get(f"{project_name}-{environment}-alb", albs.arn)
    pulumi.log.info(f"✓ Found existing ALB: {project_name}-{environment}-alb")
except:
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

# Try to find existing target group
try:
    tgs = aws.lb.get_target_group(name=f"{project_name}-default-tg")
    default_tg = aws.lb.TargetGroup.get(f"{project_name}-default-tg", tgs.arn)
    pulumi.log.info(f"✓ Found existing target group: {project_name}-default-tg")
except:
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

# Try to find existing listener
try:
    listeners = aws.lb.get_listener(
        load_balancer_arn=alb.arn,
        port=80
    )
    http_listener = aws.lb.Listener.get(f"{project_name}-http-listener", listeners.arn)
    pulumi.log.info(f"✓ Found existing HTTP listener")
except:
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
