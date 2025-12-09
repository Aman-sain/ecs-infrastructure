import boto3
import json
import time

def launch_jenkins():
    print("🚀 Launching Jenkins Server...")

    ec2 = boto3.client('ec2', region_name='us-east-1')

    # Find VPC by tag
    project = 'auto-deploy'
    env = 'prod'
    vpc_id = None
    subnet_id = None
    
    print("🔍 Searching for infrastructure...")
    
    vpcs = ec2.describe_vpcs(Filters=[
        {'Name': 'tag:Name', 'Values': [f'{project}-{env}-vpc']}
    ])
    
    if vpcs['Vpcs']:
        vpc_id = vpcs['Vpcs'][0]['VpcId']
        print(f"✓ Found VPC: {vpc_id}")
    else:
        print("❌ VPC not found. Please run infra deployment first.")
        return

    # Find Public Subnet
    subnets = ec2.describe_subnets(Filters=[
        {'Name': 'vpc-id', 'Values': [vpc_id]},
        {'Name': 'tag:Type', 'Values': ['public']}
    ])
    
    if subnets['Subnets']:
        # Sort by availability zone to pick a random/first one
        subnet_id = subnets['Subnets'][0]['SubnetId']
        print(f"✓ Found Subnet: {subnet_id}")
    else:
        print("❌ Public subnets not found.")
        return
        
    region = 'us-east-1'

    # 1. Create Security Group
    sg_name = 'jenkins-server-sg'
    try:
        sgs = ec2.describe_security_groups(Filters=[
            {'Name': 'group-name', 'Values': [sg_name]},
            {'Name': 'vpc-id', 'Values': [vpc_id]}
        ])
        if sgs['SecurityGroups']:
            sg_id = sgs['SecurityGroups'][0]['GroupId']
            print(f"✓ Found existing SG: {sg_id}")
        else:
            sg = ec2.create_security_group(
                GroupName=sg_name,
                Description='Jenkins Server Security Group',
                VpcId=vpc_id
            )
            sg_id = sg['GroupId']
            
            # Allow SSH and Jenkins UI
            ec2.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                    {'IpProtocol': 'tcp', 'FromPort': 8080, 'ToPort': 8080, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
                ]
            )
            print(f"✓ Created SG: {sg_id}")
    except Exception as e:
        print(f"❌ Error creating SG: {e}")
        return

    # 2. Key Pair (use existing 'major' if possible, or create one)
    key_name = 'major' 
    # Check if key exists
    try:
        ec2.describe_key_pairs(KeyNames=[key_name])
        print(f"✓ Using KeyPair: {key_name}")
    except:
        print(f"⚠️  KeyPair '{key_name}' not found. Please create it or update script.")
        # For now, proceed (launch might fail if key missing, or launch without key)
        # Assuming user has 'major.pem' implies 'major' key exists in AWS console? 
        # Actually user migrated to NEW account. Key might NOT exist in new account.
        # We should create it if missing, but we need the public key content.
        # Can't create from PEM.
        # We will create a new temporary key for Jenkins.
        key_name = 'jenkins-temp-key'
        try:
            key_pair = ec2.create_key_pair(KeyName=key_name)
            private_key = key_pair['KeyMaterial']
            with open('jenkins-temp-key.pem', 'w') as f:
                f.write(private_key)
            import os
            os.chmod('jenkins-temp-key.pem', 0o400)
            print(f"✓ Created and SAVED new KeyPair: {key_name} -> jenkins-temp-key.pem")
        except:
            pass

    # 3. User Data (Install Jenkins on t2.micro with Swap)
    user_data = """#!/bin/bash
# Add Swap (Critical for t2.micro/1GB RAM)
dd if=/dev/zero of=/swapfile bs=128M count=16
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo "/swapfile swap swap defaults 0 0" >> /etc/fstab

yum update -y
wget -O /etc/yum.repos.d/jenkins.repo https://pkg.jenkins.io/redhat-stable/jenkins.repo
rpm --import https://pkg.jenkins.io/redhat-stable/jenkins.io-2023.key
yum upgrade -y
dnf install java-17-amazon-corretto -y
yum install jenkins -y
systemctl enable jenkins
systemctl start jenkins
yum install git -y
yum install docker -y
systemctl enable docker
systemctl start docker
usermod -a -G docker jenkins
"""

    # 4. Launch Instance
    # Amazon Linux 2023 AMI (us-east-1)
    ami_id = 'ami-0c7217cdde317cfec' # 64-bit (x86)

    try:
        instances = ec2.run_instances(
            ImageId=ami_id,
            InstanceType='t3.micro',  # Free Tier (confirmed eligible)
            KeyName=key_name,
            MinCount=1,
            MaxCount=1,
            NetworkInterfaces=[{
                'SubnetId': subnet_id,
                'DeviceIndex': 0,
                'AssociatePublicIpAddress': True,
                'Groups': [sg_id]
            }],
            UserData=user_data,
            TagSpecifications=[{
                'ResourceType': 'instance',
                'Tags': [{'Key': 'Name', 'Value': 'Jenkins-Server-FreeTier'}]
            }]
        )
        
        instance_id = instances['Instances'][0]['InstanceId']
        print(f"✓ Launching Instance: {instance_id}")
        
        print("Waiting for running state...")
        waiter = ec2.get_waiter('instance_running')
        waiter.wait(InstanceIds=[instance_id])
        
        # Get Public IP
        desc = ec2.describe_instances(InstanceIds=[instance_id])
        public_ip = desc['Reservations'][0]['Instances'][0].get('PublicIpAddress')
        
        print("\n" + "="*50)
        print(f"✅ Jenkins Server Running!")
        print(f"Instance ID: {instance_id}")
        print(f"Public IP: {public_ip}")
        print(f"URL: http://{public_ip}:8080")
        print("="*50)
        print("Note: Jenkins may take 2-3 minutes to start.")
        print("To unlock Jenkins, get the password from:")
        print("sudo cat /var/lib/jenkins/secrets/initialAdminPassword")
        
    except Exception as e:
        print(f"❌ Error launching instance: {e}")

if __name__ == '__main__':
    launch_jenkins()
