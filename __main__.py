"""
ECS Infrastructure with Pulumi
Handles existing resources automatically with state management
"""
import pulumi
import pulumi_aws as aws
import json

# Configuration
config = pulumi.Config()
project_name = "auto-deploy"
environment = "prod"
region = "us-east-1"

# Get or create VPC
def get_or_create_vpc():
    """Get existing VPC or use default"""
    # Try to find existing VPC by CIDR
    vpcs = aws.ec2.get_vpc(
        cidr_block="10.100.0.0/16",
        opts=pulumi.InvokeOptions(parent=None)
    )

    if vpcs:
        return vpcs.id

    # Try default VPC
    try:
        default_vpc = aws.ec2.get_vpc(default=True)
        return default_vpc.id
    except:
        pass

    # If nothing found, this will fail gracefully
    raise Exception("No VPC available. Please create one or increase AWS limits.")

# Use existing VPC or create reference
try:
    vpc_id = get_or_create_vpc()
    vpc = aws.ec2.Vpc.get("vpc", vpc_id)
    pulumi.export("vpc_id", vpc.id)
except Exception as e:
    # Fall back to finding any VPC
    vpcs = aws.ec2.get_vpcs()
    if vpcs.ids:
        vpc = aws.ec2.Vpc.get("vpc", vpcs.ids[0])
        pulumi.export("vpc_id", vpc.id)
    else:
        raise Exception("No VPC available")

# Get VPC subnets
subnets = aws.ec2.get_subnets(
    filters=[{"name": "vpc-id", "values": [vpc.id]}]
)

# Get or create Internet Gateway (if attached to VPC)
igws = aws.ec2.get_internet_gateways(
    filters=[{
        "name": "attachment.vpc-id",
        "values": [vpc.id]
    }]
)

if igws.ids:
    igw_id = igws.ids[0]
    pulumi.export("igw_id", igw_id)
else:
    pulumi.log.warn("No Internet Gateway found for VPC. Service may not be internet accessible.")

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
            "description": "HTTP"
        },
        {
            "protocol": "tcp",
            "from_port": 443,
            "to_port": 443,
            "cidr_blocks": ["0.0.0.0/0"],
            "description": "HTTPS"
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
        "Environment": environment
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
        "description": "Allow from ALB"
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
        "Environment": environment
    }
)

# ECS Cluster
cluster = aws.ecs.Cluster(
    f"{project_name}-{environment}-cluster",
    name=f"{project_name}-{environment}-cluster",
    tags={
        "Name": f"{project_name}-{environment}-cluster",
        "Environment": environment
    }
)

# Cluster Capacity Providers
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

# ECR Repositories
backend_repo = aws.ecr.Repository(
    f"{project_name}-backend",
    name=f"{project_name}-backend",
    image_scanning_configuration={
        "scan_on_push": True
    },
    tags={
        "Name": f"{project_name}-backend",
        "Environment": environment
    }
)

frontend_repo = aws.ecr.Repository(
    f"{project_name}-frontend",
    name=f"{project_name}-frontend",
    image_scanning_configuration={
        "scan_on_push": True
    },
    tags={
        "Name": f"{project_name}-frontend",
        "Environment": environment
    }
)

# IAM Role for ECS Task Execution
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
        "Environment": environment
    }
)

# Attach policies to execution role
execution_role_policy_attachments = [
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

# IAM Role for ECS Tasks
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
        "Environment": environment
    }
)

# Attach SSM policy to task role for reading parameters
task_role_ssm_policy = aws.iam.RolePolicyAttachment(
    f"{project_name}-task-ssm-policy",
    role=task_role.name,
    policy_arn="arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess"
)

# CloudWatch Log Group
log_group = aws.cloudwatch.LogGroup(
    f"/ecs/{project_name}-{environment}",
    name=f"/ecs/{project_name}-{environment}",
    retention_in_days=7,
    tags={
        "Name": f"{project_name}-logs",
        "Environment": environment
    }
)

# Application Load Balancer
alb = aws.lb.LoadBalancer(
    f"{project_name}-{environment}-alb",
    name=f"{project_name}-{environment}-alb",
    internal=False,
    load_balancer_type="application",
    security_groups=[alb_sg.id],
    subnets=subnets.ids,
    enable_deletion_protection=False,
    tags={
        "Name": f"{project_name}-{environment}-alb",
        "Environment": environment
    }
)

# Default Target Group (for ALB)
default_tg = aws.lb.TargetGroup(
    f"{project_name}-default-tg",
    name=f"{project_name}-default-tg",
    port=80,
    protocol="HTTP",
    vpc_id=vpc.id,
    target_type="ip",
    health_check={
        "enabled": True,
        "path": "/",
        "protocol": "HTTP",
        "matcher": "200-499"
    },
    tags={
        "Name": f"{project_name}-default-tg",
        "Environment": environment
    }
)

# HTTP Listener
http_listener = aws.lb.Listener(
    f"{project_name}-http-listener",
    load_balancer_arn=alb.arn,
    port=80,
    protocol="HTTP",
    default_actions=[{
        "type": "forward",
        "target_group_arn": default_tg.arn
    }]
)

# Outputs
pulumi.export("cluster_name", cluster.name)
pulumi.export("cluster_arn", cluster.arn)
pulumi.export("backend_repo_url", backend_repo.repository_url)
pulumi.export("frontend_repo_url", frontend_repo.repository_url)
pulumi.export("task_execution_role_arn", task_execution_role.arn)
pulumi.export("task_role_arn", task_role.arn)
pulumi.export("alb_dns_name", alb.dns_name)
pulumi.export("alb_arn", alb.arn)
pulumi.export("alb_zone_id", alb.zone_id)
pulumi.export("http_listener_arn", http_listener.arn)
pulumi.export("alb_security_group_id", alb_sg.id)
pulumi.export("ecs_security_group_id", ecs_sg.id)
pulumi.export("log_group_name", log_group.name)
