pipeline {
    agent any

    environment {
        AWS_REGION = 'us-east-1'
        PROJECT = 'auto-deploy'
    }

    options {
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    stages {
        stage('🔍 Validate Infrastructure') {
            steps {
                script {
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    echo "🔍 Validating Infrastructure Configuration"
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                }
                sh '''
                    python3 --version
                    pip3 install -q boto3 pyyaml
                    python3 deploy-infra.py --validate || true
                '''
            }
        }

        stage('🏗️ Deploy Infrastructure') {
            steps {
                script {
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    echo "🏗️ Deploying AWS Infrastructure"
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                }
                sh '''
                    python3 deploy-infra.py
                '''
            }
        }

        stage('📊 Export Outputs') {
            steps {
                script {
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    echo "📊 Exporting Infrastructure Outputs"
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                }
                sh '''
                    # Save infrastructure outputs for service deployments
                    if [ -f /tmp/infra-config.json ]; then
                        cat /tmp/infra-config.json
                        echo "✓ Infrastructure configuration saved"
                    fi
                '''
            }
        }

        stage('🧹 Cleanup Old Resources') {
            steps {
                script {
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    echo "🧹 Cleaning Up Old Resources"
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                }
                sh '''
                    # Cleanup old unused resources
                    echo "Checking for unused target groups..."
                    aws elbv2 describe-target-groups --region ${AWS_REGION} \
                        --query "TargetGroups[?contains(TargetGroupName, 'auto-')].TargetGroupName" \
                        --output text || true

                    echo "Checking for unused task definitions..."
                    aws ecs list-task-definitions --region ${AWS_REGION} \
                        --family-prefix ${PROJECT} \
                        --status INACTIVE || true
                '''
            }
        }
    }

    post {
        success {
            script {
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo "✅ INFRASTRUCTURE DEPLOYMENT SUCCESSFUL"
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

                def infraDetails = ""
                if (fileExists('/tmp/infra-config.json')) {
                    infraDetails = readFile('/tmp/infra-config.json')
                }

                emailext (
                    subject: "✅ Infrastructure Deployment Successful",
                    body: """
                    <h2>✅ Infrastructure Deployed Successfully!</h2>
                    <table border="1" cellpadding="10">
                        <tr><td><b>Job</b></td><td>${env.JOB_NAME}</td></tr>
                        <tr><td><b>Build</b></td><td>#${env.BUILD_NUMBER}</td></tr>
                        <tr><td><b>Project</b></td><td>${env.PROJECT}</td></tr>
                        <tr><td><b>Region</b></td><td>${env.AWS_REGION}</td></tr>
                    </table>
                    <h3>Resources Created:</h3>
                    <ul>
                        <li>VPC with public/private subnets</li>
                        <li>ECS Fargate Cluster</li>
                        <li>Application Load Balancer</li>
                        <li>ECR Repositories</li>
                        <li>IAM Roles</li>
                        <li>CloudWatch Log Groups</li>
                    </ul>
                    <p><b>Configuration:</b></p>
                    <pre>${infraDetails}</pre>
                    <p><a href='${env.BUILD_URL}console'>View Console Output</a></p>
                    """,
                    to: 'vibhavhaneja2004@gmail.com',
                    mimeType: 'text/html'
                )
            }
        }

        failure {
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo "❌ INFRASTRUCTURE DEPLOYMENT FAILED"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

            emailext (
                subject: "❌ Infrastructure Deployment Failed",
                body: """
                <h2>❌ Infrastructure Deployment Failed</h2>
                <table border="1" cellpadding="10">
                    <tr><td><b>Job</b></td><td>${env.JOB_NAME}</td></tr>
                    <tr><td><b>Build</b></td><td>#${env.BUILD_NUMBER}</td></tr>
                    <tr><td><b>Status</b></td><td><span style="color:red">FAILED</span></td></tr>
                </table>
                <p>Please check the logs for details.</p>
                <p><a href='${env.BUILD_URL}console'>View Console Output</a></p>
                """,
                to: 'vibhavhaneja2004@gmail.com',
                mimeType: 'text/html'
            )
        }

        always {
            cleanWs(deleteDirs: true, disableDeferredWipeout: true)
        }
    }
}
