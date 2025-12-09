pipeline {
    agent any

    environment {
        AWS_REGION = 'us-east-1'
        AWS_DEFAULT_REGION = 'us-east-1'
    }

    options {
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    stages {
        stage('🔍 Setup Environment') {
            steps {
                script {
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    echo "🔍 Setting up Deployment Environment"
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                }
                sh '''
                    # Install Python dependencies
                    python3 -m venv venv
                    . venv/bin/activate
                    pip install boto3
                '''
            }
        }

        stage('🏗️ Deploy Infrastructure') {
            steps {
                script {
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    echo "🏗️ Deploying Infrastructure with Python"
                    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                }
                sh '''
                    . venv/bin/activate
                    python3 deploy-infra.py
                '''
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
        }
    }
}
