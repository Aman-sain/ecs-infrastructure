#!/usr/bin/env python3
"""
Infrastructure Deployment Script
Creates ALL required AWS infrastructure using boto3
No Terraform needed!
"""

import boto3
import json
import time
import sys
from botocore.exceptions import ClientError

class InfrastructureDeployer:
    def __init__(self):
        self.region = 'us-east-1'
        self.project = 'auto-deploy'
        self.env = 'prod'

        self.ec2 = boto3.client('ec2', region_name=self.region)
        self.elbv2 = boto3.client('elbv2', region_name=self.region)
        self.ecs = boto3.client('ecs', region_name=self.region)
        self.ecr = boto3.client('ecr', region_name=self.region)
        self.iam = boto3.client('iam', region_name=self.region)
        self.logs = boto3.client('logs', region_name=self.region)
        self.route53 = boto3.client('route53', region_name=self.region)
        self.acm = boto3.client('acm', region_name=self.region)
        self.sts = boto3.client('sts', region_name=self.region)

        self.account_id = self.sts.get_caller_identity()['Account']
        self.cluster_name = f"{self.project}-{self.env}-cluster"

    def log(self, message, emoji="📦"):
        print(f"{emoji} {message}")

    def get_or_create_vpc(self):
        """Create VPC or get existing"""
        self.log("Creating/Getting VPC")

        # Check if exists
        vpcs = self.ec2.describe_vpcs(Filters=[
            {'Name': 'tag:Name', 'Values': [f'{self.project}-{self.env}-vpc']}
        ])

        if vpcs['Vpcs']:
            vpc_id = vpcs['Vpcs'][0]['VpcId']
            self.log(f"Found existing VPC: {vpc_id}", "✓")
        else:
            vpc = self.ec2.create_vpc(CidrBlock='10.100.0.0/16')
            vpc_id = vpc['Vpc']['VpcId']

            self.ec2.create_tags(Resources=[vpc_id], Tags=[
                {'Key': 'Name', 'Value': f'{self.project}-{self.env}-vpc'}
            ])

            self.ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={'Value': True})
            self.ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={'Value': True})

            self.log(f"Created VPC: {vpc_id}", "✓")

        return vpc_id

    def get_or_create_igw(self, vpc_id):
        """Create Internet Gateway"""
        self.log("Creating/Getting Internet Gateway")

        igws = self.ec2.describe_internet_gateways(Filters=[
            {'Name': 'tag:Name', 'Values': [f'{self.project}-{self.env}-igw']}
        ])

        if igws['InternetGateways']:
            igw_id = igws['InternetGateways'][0]['InternetGatewayId']
            self.log(f"Found existing IGW: {igw_id}", "✓")
        else:
            igw = self.ec2.create_internet_gateway()
            igw_id = igw['InternetGateway']['InternetGatewayId']

            self.ec2.create_tags(Resources=[igw_id], Tags=[
                {'Key': 'Name', 'Value': f'{self.project}-{self.env}-igw'}
            ])

            try:
                self.ec2.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
            except ClientError as e:
                if 'Resource.AlreadyAssociated' not in str(e):
                    raise

            self.log(f"Created IGW: {igw_id}", "✓")

        return igw_id

    def create_subnets(self, vpc_id):
        """Create public and private subnets"""
        self.log("Creating Subnets")

        azs = self.ec2.describe_availability_zones()['AvailabilityZones'][:3]
        public_subnets = []
        private_subnets = []

        for i, az in enumerate(azs):
            az_name = az['ZoneName']

            # Public subnet
            pub_name = f'{self.project}-{self.env}-public-{i}'
            pub_subnets = self.ec2.describe_subnets(Filters=[
                {'Name': 'vpc-id', 'Values': [vpc_id]},
                {'Name': 'tag:Name', 'Values': [pub_name]}
            ])

            if pub_subnets['Subnets']:
                pub_subnet_id = pub_subnets['Subnets'][0]['SubnetId']
            else:
                pub_subnet = self.ec2.create_subnet(
                    VpcId=vpc_id,
                    CidrBlock=f'10.100.{i}.0/24',
                    AvailabilityZone=az_name
                )
                pub_subnet_id = pub_subnet['Subnet']['SubnetId']

                self.ec2.create_tags(Resources=[pub_subnet_id], Tags=[
                    {'Key': 'Name', 'Value': pub_name},
                    {'Key': 'Type', 'Value': 'public'}
                ])

                self.ec2.modify_subnet_attribute(
                    SubnetId=pub_subnet_id,
                    MapPublicIpOnLaunch={'Value': True}
                )

            public_subnets.append(pub_subnet_id)

            # Private subnet
            priv_name = f'{self.project}-{self.env}-private-{i}'
            priv_subnets = self.ec2.describe_subnets(Filters=[
                {'Name': 'vpc-id', 'Values': [vpc_id]},
                {'Name': 'tag:Name', 'Values': [priv_name]}
            ])

            if priv_subnets['Subnets']:
                priv_subnet_id = priv_subnets['Subnets'][0]['SubnetId']
            else:
                priv_subnet = self.ec2.create_subnet(
                    VpcId=vpc_id,
                    CidrBlock=f'10.100.{100+i}.0/24',
                    AvailabilityZone=az_name
                )
                priv_subnet_id = priv_subnet['Subnet']['SubnetId']

                self.ec2.create_tags(Resources=[priv_subnet_id], Tags=[
                    {'Key': 'Name', 'Value': priv_name},
                    {'Key': 'Type', 'Value': 'private'}
                ])

            private_subnets.append(priv_subnet_id)

        self.log(f"Subnets ready: {len(public_subnets)} public, {len(private_subnets)} private", "✓")
        return public_subnets, private_subnets

    def create_nat_gateway(self, public_subnet_id):
        """Create NAT Gateway"""
        self.log("Creating NAT Gateway (this may take a few minutes)")

        # Check if NAT exists
        nats = self.ec2.describe_nat_gateways(Filters=[
            {'Name': 'subnet-id', 'Values': [public_subnet_id]},
            {'Name': 'state', 'Values': ['available', 'pending']}
        ])

        if nats['NatGateways']:
            nat_id = nats['NatGateways'][0]['NatGatewayId']
            self.log(f"Found existing NAT: {nat_id}", "✓")

            # Wait for it to be available
            while True:
                nat = self.ec2.describe_nat_gateways(NatGatewayIds=[nat_id])['NatGateways'][0]
                if nat['State'] == 'available':
                    break
                self.log("Waiting for NAT Gateway...")
                time.sleep(10)
        else:
            # Allocate EIP
            eip = self.ec2.allocate_address(Domain='vpc')
            eip_id = eip['AllocationId']

            self.ec2.create_tags(Resources=[eip_id], Tags=[
                {'Key': 'Name', 'Value': f'{self.project}-{self.env}-nat-eip'}
            ])

            # Create NAT
            nat = self.ec2.create_nat_gateway(SubnetId=public_subnet_id, AllocationId=eip_id)
            nat_id = nat['NatGateway']['NatGatewayId']

            # Wait for NAT to be available
            self.log("Waiting for NAT Gateway to become available...")
            while True:
                nat = self.ec2.describe_nat_gateways(NatGatewayIds=[nat_id])['NatGateways'][0]
                if nat['State'] == 'available':
                    break
                time.sleep(10)

            self.log(f"NAT Gateway ready: {nat_id}", "✓")

        return nat_id

    def create_route_tables(self, vpc_id, igw_id, nat_id, public_subnets, private_subnets):
        """Create route tables"""
        self.log("Creating Route Tables")

        # Public route table
        pub_rts = self.ec2.describe_route_tables(Filters=[
            {'Name': 'vpc-id', 'Values': [vpc_id]},
            {'Name': 'tag:Name', 'Values': [f'{self.project}-{self.env}-public-rt']}
        ])

        if pub_rts['RouteTables']:
            pub_rt_id = pub_rts['RouteTables'][0]['RouteTableId']
        else:
            pub_rt = self.ec2.create_route_table(VpcId=vpc_id)
            pub_rt_id = pub_rt['RouteTable']['RouteTableId']

            self.ec2.create_tags(Resources=[pub_rt_id], Tags=[
                {'Key': 'Name', 'Value': f'{self.project}-{self.env}-public-rt'}
            ])

            self.ec2.create_route(RouteTableId=pub_rt_id, DestinationCidrBlock='0.0.0.0/0', GatewayId=igw_id)

            for subnet in public_subnets:
                try:
                    self.ec2.associate_route_table(RouteTableId=pub_rt_id, SubnetId=subnet)
                except ClientError:
                    pass

        # Private route table
        priv_rts = self.ec2.describe_route_tables(Filters=[
            {'Name': 'vpc-id', 'Values': [vpc_id]},
            {'Name': 'tag:Name', 'Values': [f'{self.project}-{self.env}-private-rt']}
        ])

        if priv_rts['RouteTables']:
            priv_rt_id = priv_rts['RouteTables'][0]['RouteTableId']
        else:
            priv_rt = self.ec2.create_route_table(VpcId=vpc_id)
            priv_rt_id = priv_rt['RouteTable']['RouteTableId']

            self.ec2.create_tags(Resources=[priv_rt_id], Tags=[
                {'Key': 'Name', 'Value': f'{self.project}-{self.env}-private-rt'}
            ])

            self.ec2.create_route(RouteTableId=priv_rt_id, DestinationCidrBlock='0.0.0.0/0', NatGatewayId=nat_id)

            for subnet in private_subnets:
                try:
                    self.ec2.associate_route_table(RouteTableId=priv_rt_id, SubnetId=subnet)
                except ClientError:
                    pass

        self.log("Route tables ready", "✓")

    def create_security_groups(self, vpc_id):
        """Create security groups"""
        self.log("Creating Security Groups")

        # ALB SG
        alb_sgs = self.ec2.describe_security_groups(Filters=[
            {'Name': 'vpc-id', 'Values': [vpc_id]},
            {'Name': 'group-name', 'Values': [f'{self.project}-{self.env}-alb-sg']}
        ])

        if alb_sgs['SecurityGroups']:
            alb_sg_id = alb_sgs['SecurityGroups'][0]['GroupId']
        else:
            alb_sg = self.ec2.create_security_group(
                GroupName=f'{self.project}-{self.env}-alb-sg',
                Description='ALB Security Group',
                VpcId=vpc_id
            )
            alb_sg_id = alb_sg['GroupId']

            self.ec2.authorize_security_group_ingress(
                GroupId=alb_sg_id,
                IpPermissions=[
                    {'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                    {'IpProtocol': 'tcp', 'FromPort': 443, 'ToPort': 443, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
                ]
            )

        # ECS SG
        ecs_sgs = self.ec2.describe_security_groups(Filters=[
            {'Name': 'vpc-id', 'Values': [vpc_id]},
            {'Name': 'group-name', 'Values': [f'{self.project}-{self.env}-ecs-sg']}
        ])

        if ecs_sgs['SecurityGroups']:
            ecs_sg_id = ecs_sgs['SecurityGroups'][0]['GroupId']
        else:
            ecs_sg = self.ec2.create_security_group(
                GroupName=f'{self.project}-{self.env}-ecs-sg',
                Description='ECS Tasks Security Group',
                VpcId=vpc_id
            )
            ecs_sg_id = ecs_sg['GroupId']

            self.ec2.authorize_security_group_ingress(
                GroupId=ecs_sg_id,
                IpPermissions=[{
                    'IpProtocol': 'tcp',
                    'FromPort': 0,
                    'ToPort': 65535,
                    'UserIdGroupPairs': [{'GroupId': alb_sg_id}]
                }]
            )

        self.log(f"Security groups ready", "✓")
        return alb_sg_id, ecs_sg_id

    def get_or_create_certificate(self):
        """Get or create SSL certificate"""
        self.log("Checking SSL Certificate")

        certs = self.acm.list_certificates()
        for cert in certs['CertificateSummaryList']:
            if cert['DomainName'] == 'webbyftw.co.in':
                cert_arn = cert['CertificateArn']
                cert_details = self.acm.describe_certificate(CertificateArn=cert_arn)
                if cert_details['Certificate']['Status'] == 'ISSUED':
                    self.log(f"Found valid certificate", "✓")
                    return cert_arn

        self.log("⚠️  No valid SSL certificate found. Please create one manually:", "⚠️")
        self.log("aws acm request-certificate --domain-name webbyftw.co.in --subject-alternative-names '*.webbyftw.co.in' --validation-method DNS --region us-east-1")
        return None

    def create_alb(self, vpc_id, public_subnets, alb_sg_id, cert_arn):
        """Create Application Load Balancer"""
        self.log("Creating Application Load Balancer")

        # Check if exists
        try:
            albs = self.elbv2.describe_load_balancers(Names=[f'{self.project}-{self.env}-alb'])
            alb_arn = albs['LoadBalancers'][0]['LoadBalancerArn']
            alb_dns = albs['LoadBalancers'][0]['DNSName']
            alb_zone = albs['LoadBalancers'][0]['CanonicalHostedZoneId']
            self.log(f"Found existing ALB", "✓")
        except:
            alb = self.elbv2.create_load_balancer(
                Name=f'{self.project}-{self.env}-alb',
                Subnets=public_subnets,
                SecurityGroups=[alb_sg_id],
                Scheme='internet-facing',
                Type='application'
            )
            alb_arn = alb['LoadBalancers'][0]['LoadBalancerArn']
            alb_dns = alb['LoadBalancers'][0]['DNSName']
            alb_zone = alb['LoadBalancers'][0]['CanonicalHostedZoneId']

            self.log("Waiting for ALB to be active...")
            waiter = self.elbv2.get_waiter('load_balancer_available')
            waiter.wait(LoadBalancerArns=[alb_arn])

            self.log(f"ALB ready: {alb_dns}", "✓")

        # Create listeners
        try:
            listeners = self.elbv2.describe_listeners(LoadBalancerArn=alb_arn)
            https_listener = [l for l in listeners['Listeners'] if l['Port'] == 443]
            if https_listener:
                https_listener_arn = https_listener[0]['ListenerArn']
                self.log("Found existing HTTPS listener", "✓")
            else:
                raise Exception("Need to create listeners")
        except:
            # HTTP listener (redirect to HTTPS)
            self.elbv2.create_listener(
                LoadBalancerArn=alb_arn,
                Protocol='HTTP',
                Port=80,
                DefaultActions=[{
                    'Type': 'redirect',
                    'RedirectConfig': {
                        'Protocol': 'HTTPS',
                        'Port': '443',
                        'StatusCode': 'HTTP_301'
                    }
                }]
            )

            # HTTPS listener
            if cert_arn:
                https_listener_response = self.elbv2.create_listener(
                    LoadBalancerArn=alb_arn,
                    Protocol='HTTPS',
                    Port=443,
                    Certificates=[{'CertificateArn': cert_arn}],
                    DefaultActions=[{
                        'Type': 'fixed-response',
                        'FixedResponseConfig': {
                            'StatusCode': '404',
                            'ContentType': 'text/plain',
                            'MessageBody': 'Not Found'
                        }
                    }]
                )
                https_listener_arn = https_listener_response['Listeners'][0]['ListenerArn']
                self.log("HTTPS listener created", "✓")
            else:
                https_listener_arn = None

        return alb_arn, alb_dns, alb_zone, https_listener_arn

    def create_ecs_cluster(self):
        """Create ECS cluster"""
        self.log("Creating ECS Cluster")

        try:
            self.ecs.create_cluster(
                clusterName=self.cluster_name,
                capacityProviders=['FARGATE', 'FARGATE_SPOT'],
                defaultCapacityProviderStrategy=[
                    {'capacityProvider': 'FARGATE', 'weight': 1, 'base': 1}
                ]
            )
            self.log(f"ECS Cluster created: {self.cluster_name}", "✓")
        except ClientError as e:
            if 'ClusterAlreadyExistsException' in str(e):
                self.log(f"ECS Cluster already exists", "✓")
            else:
                raise

    def create_ecr_repositories(self):
        """Create ECR repositories"""
        self.log("Creating ECR Repositories")

        for repo in ['backend', 'frontend']:
            repo_name = f'{self.project}-{repo}'
            try:
                self.ecr.create_repository(
                    repositoryName=repo_name,
                    imageScanningConfiguration={'scanOnPush': True}
                )
                self.log(f"ECR repo created: {repo_name}", "✓")
            except ClientError as e:
                if 'RepositoryAlreadyExistsException' in str(e):
                    self.log(f"ECR repo exists: {repo_name}", "✓")
                else:
                    raise

    def create_iam_roles(self):
        """Create IAM roles"""
        self.log("Creating IAM Roles")

        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }

        # Task Execution Role
        exec_role_name = f'{self.project}-ecs-execution-role'
        try:
            self.iam.create_role(
                RoleName=exec_role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy)
            )
            self.iam.attach_role_policy(
                RoleName=exec_role_name,
                PolicyArn='arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy'
            )

            # Add SSM permissions
            self.iam.put_role_policy(
                RoleName=exec_role_name,
                PolicyName='ssm-secrets',
                PolicyDocument=json.dumps({
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Effect": "Allow",
                        "Action": [
                            "ssm:GetParameters",
                            "ssm:GetParameter",
                            "secretsmanager:GetSecretValue",
                            "kms:Decrypt"
                        ],
                        "Resource": "*"
                    }]
                })
            )
            self.log(f"Execution role created", "✓")
        except ClientError as e:
            if 'EntityAlreadyExists' in str(e):
                self.log(f"Execution role exists", "✓")
            else:
                raise

        # Task Role
        task_role_name = f'{self.project}-ecs-task-role'
        try:
            self.iam.create_role(
                RoleName=task_role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy)
            )
            self.iam.put_role_policy(
                RoleName=task_role_name,
                PolicyName='task-permissions',
                PolicyDocument=json.dumps({
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Effect": "Allow",
                        "Action": [
                            "ssm:GetParameters",
                            "ssm:GetParameter",
                            "dynamodb:*",
                            "s3:*"
                        ],
                        "Resource": "*"
                    }]
                })
            )
            self.log(f"Task role created", "✓")
        except ClientError as e:
            if 'EntityAlreadyExists' in str(e):
                self.log(f"Task role exists", "✓")
            else:
                raise

    def create_cloudwatch_logs(self):
        """Create CloudWatch log group"""
        self.log("Creating CloudWatch Log Group")

        log_group = f'/ecs/{self.project}-{self.env}'
        try:
            self.logs.create_log_group(logGroupName=log_group)
            self.logs.put_retention_policy(logGroupName=log_group, retentionInDays=7)
            self.log(f"Log group created", "✓")
        except ClientError as e:
            if 'ResourceAlreadyExistsException' in str(e):
                self.log(f"Log group exists", "✓")
            else:
                raise

    def deploy(self):
        """Deploy all infrastructure"""
        print("\n" + "="*60)
        print("🚀 Deploying ECS Auto-Deploy Infrastructure")
        print("="*60 + "\n")

        # Network layer
        vpc_id = self.get_or_create_vpc()
        igw_id = self.get_or_create_igw(vpc_id)
        public_subnets, private_subnets = self.create_subnets(vpc_id)
        nat_id = self.create_nat_gateway(public_subnets[0])
        self.create_route_tables(vpc_id, igw_id, nat_id, public_subnets, private_subnets)

        # Security
        alb_sg_id, ecs_sg_id = self.create_security_groups(vpc_id)

        # Certificate
        cert_arn = self.get_or_create_certificate()

        # Load Balancer
        alb_arn, alb_dns, alb_zone, https_listener_arn = self.create_alb(
            vpc_id, public_subnets, alb_sg_id, cert_arn
        )

        # ECS
        self.create_ecs_cluster()
        self.create_ecr_repositories()
        self.create_iam_roles()
        self.create_cloudwatch_logs()

        # Save config
        config = {
            'vpc_id': vpc_id,
            'public_subnets': public_subnets,
            'private_subnets': private_subnets,
            'alb_arn': alb_arn,
            'alb_dns': alb_dns,
            'alb_zone': alb_zone,
            'https_listener_arn': https_listener_arn,
            'ecs_sg_id': ecs_sg_id,
            'cluster_name': self.cluster_name,
            'account_id': self.account_id,
            'region': self.region
        }

        with open('/tmp/infra-config.json', 'w') as f:
            json.dump(config, f, indent=2)

        print("\n" + "="*60)
        print("✅ Infrastructure Deployed Successfully!")
        print("="*60)
        print(f"\nVPC: {vpc_id}")
        print(f"ECS Cluster: {self.cluster_name}")
        print(f"ALB DNS: {alb_dns}")
        print(f"HTTPS Listener: {https_listener_arn or 'None (need cert)'}")
        print(f"\nConfig saved to: /tmp/infra-config.json")
        print(f"\n📌 Next: Deploy services with deploy.py\n")

if __name__ == '__main__':
    deployer = InfrastructureDeployer()
    deployer.deploy()
