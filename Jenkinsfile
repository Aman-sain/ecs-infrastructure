pipeline {
    agent any

    environment {
        AWS_REGION = 'us-east-1'
        AWS_DEFAULT_REGION = 'us-east-1'
        PULUMI_BACKEND_URL = "s3://terraform-state-ecs-autodeploy-724772079986/pulumi"
    }

    options {
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    stages {
        stage('🔍 Setup Pulumi') {
            steps {
                script {
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    echo "🔍 Setting up Pulumi"
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                }
                sh '''
                    # Install Pulumi
                    curl -fsSL https://get.pulumi.com | sh
                    export PATH=$PATH:$HOME/.pulumi/bin

                    # Verify installation
                    pulumi version

                    # Install Python dependencies
                    pip3 install --quiet -r requirements.txt

                    # Login to S3 backend
                    pulumi login ${PULUMI_BACKEND_URL}
                '''
            }
        }

        stage('🏗️ Deploy Infrastructure') {
            steps {
                script {
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    echo "🏗️ Deploying Infrastructure with Pulumi"
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                }
                sh '''
                    export PATH=$PATH:$HOME/.pulumi/bin

                    # Select or create stack
                    pulumi stack select prod --create || pulumi stack select prod

                    # Preview changes
                    echo "📋 Preview of changes:"
                    pulumi preview --non-interactive

                    # Deploy
                    echo "🚀 Deploying infrastructure..."
                    pulumi up --yes --non-interactive

                    # Export outputs
                    echo "📊 Infrastructure outputs:"
                    pulumi stack output --json > infrastructure-outputs.json
                    cat infrastructure-outputs.json
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
                    export PATH=$PATH:$HOME/.pulumi/bin

                    # Archive outputs
                    pulumi stack output --json | tee pulumi-outputs.json

                    echo "✓ Infrastructure outputs saved"
                '''

                archiveArtifacts artifacts: 'pulumi-outputs.json', fingerprint: true
            }
        }
    }

    post {
        always {
            cleanWs()
        }
        success {
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo "✅ INFRASTRUCTURE DEPLOYED SUCCESSFULLY"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        }
        failure {
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo "❌ INFRASTRUCTURE DEPLOYMENT FAILED"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            emailext(
                subject: "❌ Infrastructure Deployment Failed - ${env.JOB_NAME} #${env.BUILD_NUMBER}",
                body: """
                    Infrastructure deployment failed!

                    Job: ${env.JOB_NAME}
                    Build: ${env.BUILD_NUMBER}
                    URL: ${env.BUILD_URL}

                    Check the console output for details.
                """,
                to: "vibhavhaneja2004@gmail.com"
            )
        }
    }
}
