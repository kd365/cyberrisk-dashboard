# Assessment III - CICD Pipeline with Github Actions & Docker Compose

---

## **Overview**

This assessment evaluates your understanding of Continuous Integration & Continuous Deployment concepts utilizing containerization and automation through GitHub Actions.

Your goal is to automate the deployment of a three-tier application stack through a CICD pipeline.  Your stack must include a front end app and web server, a back end API and a database.  

You can use any application you've worked on so far during this cohort.  Our example will expand on the application built in assessment 2.

To do this, you'll need to understand how to manage secrets and environment variables, how to containerize and orchestrate artifacts using Docker and Docker Compose, and how to write Github Actions Workflows to sequentially execute all necessary actions. 

Both Flask applications are simple applications with basic logic built in.  Your goal is simply to provision the infrastructure to support it, and to automate the setup of the resources necessary for it to run.

---

## **Objectives**

The core goal is to set up an automated CI/CD process utilizing workflows and containerization on top of everything else you've learned so far in this curriculum.  To do this, you must meet these objectives:

1. Manage the transfer and use of secrets and variables across multiple environments  
2. Build, push, pull, run and deploy containerized instances of your application's components  
3. Automate the delivery of your app using workflows such that you can trigger the release of your application publicly with minimal manual intervention

We can outline these objectives to give you an idea of what will be scored. 

## **Exam Outline**

**1. Integration of Mem0 and Langchain (25%)**

1. Implement LangChain chains to orchestrate multi-step AI workflows wiht proper prompt templates
2. Build a Retrieval-Augmented Generation (RAG) pipeline with document loading, text splitting, embeddings, and vector store integration
3. Integrate Mem0 API for semantic memory storage and LangChain conversation memory for session-level context management
4. Bonus points for LangGraph workflows, LangSmith observability, or custom autonomous agents

**2. Terraform Infrastructure as Code (10%)**

1. Create Terraform configurations for provisioning all necessary cloud resources
2. Implement proper state management and backend configuration
3. Bonus points for optimization & best practices (modules, variables, outputs, workspaces, remote state, proper resource dependencies, etc)

**3. Github Actions (30%)**

1. Configure GitHub Actions workflows to automate the build and push process.  
2. Demonstrate an ability to both utilize pre-built Actions and to write necessary job steps  
3. Avoid the use of any hard-coded values in application code.  Securely store and pass secrets, keys and vars in Github Actions and/or AWS Secrets Manager.
4. Utilize and incorporate Dockerfiles and Docker compose
5. Write steps for testing, logging and checks into Github Actions workflow
6. Bonus points for additional pipeline design functionality (various workflows/jobs/steps triggered conditionally, additional workflows like for destroying resources)
7. Bonus points for utilizing additional frameworks like Python unit tests or Ansible for deployment


**4. Integrations (15%)**

1. Integrate AWS Bedrock/Open AI agents for AI-powered functionality or custom models using Ollama 
2. Integrate your app's functionality into an application backend API
3. Integrate front end component for interacting with your app
4. Bonus points for integrating system level UI and making it accessible through a browser

**5. Documentation & Code Comments (20%)**

1. Provide clear documentation outlining all setup and configuration steps.  Another user should be able to follow your instructions and achieve the same results.  
2. Provide at least two additional resources such as diagrams of the overall architecture, internal components, database schema, etc.  
3. Ability to present and talk through project and answer questions  
4. All deliverables viewable through a Github repository  
5. Bonus points for presenting early, points deducted for presenting late
6. Bonus points for utilizing shell scripts to assist with set up (setting up vars/secrets, file scaffolding, pushing changes, tests, etc)

---

## **Deliverables** 

Systems and applications are only as effective as their ease of use.  All of the following should be provided in a way that a team member or colleague can repeat your entire flow.

1. Architecture diagrams of your system and/or parts of your system  
2. Documentation listing out terminal commands for repeatable set up.  
3. All necessary Github Actions workflows  
4. All necessary Docker and Docker Compose files  
5. Any additional files for minimizing automation (ex: bash scripts for adding GH secrets & vars or templating core project files)

Remember, deliverables should not only be created with functionality and performance in mind, but also for replicability and clarity.  Capability draws attention; measurable results create value.

## **Timeline**

You'll have one week to complete the assessment.  Points will be docked for every additional class day the assessment is not completed and presented.  Here are some **pro tips** to help keep you moving:

- Just like before, consider the advantage of reusability.  You can reuse configuration and workflow code either provided previously or that you've written, even if just as a foundation or starting point  
- Github Actions and Terraform outputs can be used to log convenient data to your console  
- Prebuilt Github Actions can make certain requirements much simpler

  
Good luck!

## **Hints**

- Time management is key. Go for the implementations that you're most comfortable or familiar with. You can always add on later
- You don't necessarily need to create all resources. Working resources like VPCs, security groups, roles/policies, can be shared and imported
- A working demo may be available tagged with 'aico-aiii-demo'. You can view resources tagged with this in AWS console to inspect details
- Ask questions and help one another out as needed. This *isn't* cheating. Technical abilities aren't the only skills that matter. Collaboration and communication are also crucial skills for employment
- Test LangChain chains and Mem0 integration locally before deploying to reduce debugging time
- Use LangSmith for observability early to catch issues in your chains
- Start with simple RAG pipelines before adding complexity

---

## **Troubleshooting**

### GitHub Actions Issues

- Verify GitHub secrets are properly configured (AWS credentials, API keys)
- Check workflow syntax with `act` tool or GitHub's workflow validator
- Review Actions logs in the GitHub UI for detailed error messages
- Ensure Terraform state backend is properly configured if using remote state

### Terraform Issues

- Run `terraform plan` before `apply` to catch errors early
- Check AWS credentials: `aws sts get-caller-identity`
- Verify Terraform state isn't locked: check DynamoDB lock table
- Use `terraform destroy` to clean up resources if starting fresh
- Check resource dependencies if apply fails partway through

### LangChain Integration Issues

- Verify AWS Bedrock model access in your region
- Check that embeddings model matches vector store dimensions
- Test prompts independently before integrating into chains
- Verify document loaders can access files (check paths and permissions)
- Use LangSmith tracing to debug chain execution

### Mem0 API Issues

- Verify API key is correctly configured in environment variables
- Check Mem0 API rate limits if requests are failing
- Test Mem0 connection independently before full integration
- Verify user_id and session management is consistent

### Frontend/Backend Connection Issues

- Verify API endpoints match between frontend and backend
- Check CORS configuration if browser blocks requests
- Ensure security groups allow traffic on necessary ports
- Test backend endpoints with curl or Postman before frontend integration

### EC2/Deployment Issues

- Check EC2 instance status and system logs
- Verify user data scripts executed successfully
- SSH into instance to check application logs
- Ensure IAM roles have necessary permissions for Bedrock and other services

---

[Getting Started](./getting_started.md)



# Assessment III - Getting Started

## Prerequisites

- AWS Account with appropriate permissions for Bedrock, EC2, Lambda, and other services
- Terraform installed (version 1.0+)
- GitHub account with repository created
- AWS CLI configured with credentials
- Python 3.8+ installed (for backend and local testing)
- Node.js and npm installed (for frontend)
- Git installed

## Initial Setup Steps

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd <your-repo-name>
```

### 2. Confirm AWS credential configuration

```bash
aws configure
# Verify configuration
aws sts get-caller-identity
```

### 3. Set up GitHub Secrets

Navigate to your repository: Settings → Secrets and variables → Actions

Add the following secrets:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `MEM0_API_KEY` (if using Mem0)
- `LANGCHAIN_API_KEY` (if using LangSmith)
- Any other API keys needed for your integrations

### 4. Initialize Terraform (Local Testing)

```bash
cd terraform
terraform init
terraform plan
# Review the plan but don't apply yet - let GitHub Actions handle deployment
```

### 5. Set up Backend (Flask or FastAPI)

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file with your configuration:
```
AWS_REGION=us-east-1
MEM0_API_KEY=your_mem0_key
LANGCHAIN_API_KEY=your_langchain_key
# Add other environment variables as needed
```

Test locally:
```bash
python app.py
```

### 6. Set up Frontend (React)

```bash
cd frontend
npm install
```

Configure API endpoint in `.env`:
```
REACT_APP_API_URL=http://localhost:5000
# This will be updated to production URL after deployment
```

Start development server:
```bash
npm start
```

### 7. Test LangChain and Mem0 Integration Locally

Create a test script (`backend/test_integrations.py`):
```python
from langchain_aws import ChatBedrock
from langchain.prompts import ChatPromptTemplate
# Add your test code here
```

Run tests:
```bash
python test_integrations.py
```

### 8. Configure GitHub Actions Workflow

Review `.github/workflows/deploy.yml` and ensure:
- Workflow triggers are configured (push to main, pull_request, workflow_dispatch)
- Terraform steps are properly sequenced
- Secrets are referenced correctly
- Deployment steps match your architecture

### 9. First Deployment

```bash
git add .
git commit -m "Initial setup for Assessment III"
git push origin main
```

Monitor deployment:
- Go to GitHub repository → Actions tab
- Watch workflow execution in real-time
- Check logs for any errors
- Verify resources created in AWS Console

### 10. Verify Deployment

After successful deployment:
- Check Terraform outputs for important URLs and endpoints
- Test backend API endpoints
- Access frontend application
- Verify LangChain and Mem0 integrations are working
- Test AI functionalities (chatbot, RAG, etc.)

## Recommended Development Flow

1. **Develop locally first**: Test all components on your local machine
2. **Commit to feature branch**: Work on features in separate branches
3. **Review GitHub Actions plan**: Let CI/CD run `terraform plan` on pull requests
4. **Review plan output**: Check what resources will be created/modified
5. **Merge to main**: Trigger full deployment via merge
6. **Verify in AWS**: Check AWS Console for resource creation
7. **Test application**: Verify all integrations work as expected
8. **Iterate**: Make improvements and repeat the process

## TODO List

### Terraform
- [ ] Configure VPC and networking (or import existing)
- [ ] Create EC2 instance with user data for backend deployment
- [ ] Set up security groups with appropriate ingress/egress rules
- [ ] Create IAM roles for Bedrock, Lambda, and other AWS services
- [ ] Configure database (RDS, DynamoDB, or PostgreSQL on EC2)
- [ ] Set up S3 bucket for frontend hosting (optional)
- [ ] Configure remote backend with S3 and DynamoDB for state management
- [ ] Add outputs for important values (URLs, endpoints, etc.)

### Backend
- [ ] Implement LangChain chains for AI workflows
- [ ] Build RAG pipeline with document loaders and vector stores
- [ ] Integrate Mem0 for semantic memory storage
- [ ] Configure LangChain conversation memory
- [ ] Set up AWS Bedrock client and agent integration
- [ ] Create API endpoints for frontend communication
- [ ] Implement error handling and logging
- [ ] Add health check endpoint

### Frontend
- [ ] Build UI for chat interface
- [ ] Add components for RAG document upload
- [ ] Display conversation history from Mem0
- [ ] Style the application with modern UI framework
- [ ] Configure API client to communicate with backend

### GitHub Actions
- [ ] Create workflow for Terraform plan on pull requests
- [ ] Create workflow for Terraform apply on main branch merge
- [ ] Add workflow for running tests (optional)
- [ ] Add workflow for destroying resources (optional)
- [ ] Configure proper secrets and environment variables

### Documentation
- [ ] Create architecture diagram showing all components
- [ ] Document LangChain chain architecture
- [ ] Document Mem0 memory layer design
- [ ] Create database schema diagram (if applicable)
- [ ] Document all setup and deployment steps
- [ ] Add troubleshooting guide