I need to create a Python ai agent that does the following:
* Open a port to be triggered by a Tekton pipeline via the following command (where agent_entpoint is the URL of the agent similar to http://agent.agent-user1.svc:8000/report-failure):
            echo "Looks like your pipeline failed, let's find where you messed up"
            failed_pod=$(oc get pods --field-selector="status.phase=Failed" --sort-by="status.startTime" | grep -v "trigger-agent" | grep "agent-service-build" | tail -n 1 | awk '{print $1}')
            curl -i -H "Content-Type: application/json" -X POST -d "{\"namespace\":\"{{ .Values.namespace }}\",\"pod_name\":\"${failed_pod}\",\"container_name\":\"step-buildah\"}" {{ .Values.agent_endpoint }}

* Upon triggering the logic calls a model in LiteLLM - the URL and API key are to be provided via Environment variables. The model supports tool calling to OpenShift and Gitea.
* Model Prompt can be similar to:
model_prompt = """
You are a helpful assistant. You have access to a number of tools.
Whenever a tool is called, be sure to return the Response in a friendly and helpful tone.
"""

* Build the actual prompt for the model similar to this logic:
    print(f"Building prompt for pod: {pod_name}, namespace: {namespace}")
        
        # Use .format() to avoid f-string curly brace conflicts
        prompt_template = """You are an expert OpenShift administrator. Your task is to analyze pod logs, summarize the error, and generate a JSON object to create a GitHub issue for tracking. Follow the format in the examples below.
        
        ---
        EXAMPLE 1:
        Input: The logs for pod 'frontend-v2-abcde' in namespace 'webapp' show: ImagePullBackOff: Back-off pulling image 'my-registry/frontend:latest'.

        Output:
        The pod is in an **ImagePullBackOff** state. This means Kubernetes could not pull the container image 'my-registry/frontend:latest', likely due to an incorrect image tag or authentication issues.
        {{\"name\":\"create_issue\",\"arguments\":{{\"owner\":\"redhat-ai-services\",\"repo\":\"etx-agentic-ai\",\"title\":\"Issue with Etx pipeline\",\"body\":\"### Cluster/namespace location\\nwebapp/frontend-v2-abcde\\n\\n### Summary of the problem\\nThe pod is failing to start due to an ImagePullBackOff error.\\n\\n### Detailed error/code\\nImagePullBackOff: Back-off pulling image 'my-registry/frontend:latest'\\n\\n### Possible solutions\\n1. Verify the image tag 'latest' exists in the 'my-registry/frontend' repository.\\n2. Check for authentication errors with the image registry.\"}}}}

        ---
        EXAMPLE 2:
        Input: The logs for pod 'data-processor-xyz' in namespace 'pipelines' show: CrashLoopBackOff. Last state: OOMKilled.

        Output:
        The pod is in a **CrashLoopBackOff** state because it was **OOMKilled**. The container tried to use more memory than its configured limit.
        {{\"name\":\"create_issue\",\"arguments\":{{\"owner\":\"redhat-ai-services\",\"repo\":\"etx-agentic-ai\",\"title\":\"Issue with Etx pipeline\",\"body\":\"### Cluster/namespace location\\npipelines/data-processor-xyz\\n\\n### Summary of the problem\\nThe pod is in a CrashLoopBackOff state because it was OOMKilled (Out of Memory).\\n\\n### Detailed error/code\\nCrashLoopBackOff, Last state: OOMKilled\\n\\n### Possible solutions\\n1. Increase the memory limit in the pod's deployment configuration.\\n2. Analyze the application for memory leaks.\"}}}}
        ---

        NOW, YOUR TURN:

        Input: Review the OpenShift logs for the pod '{pod_name}' in the '{namespace}' namespace. If the logs indicate an error, search for the solution, create a summary message with the category and explanation of the error, and create a Github issue using {{\"name\":\"create_issue\",\"arguments\":{{\"owner\":\"redhat-ai-services\",\"repo\":\"etx-agentic-ai\",\"title\":\"Issue with Etx pipeline\",\"body\":\"<summary of the error>\"}}}}. DO NOT add any optional parameters.

        ONLY tail the last 10 lines of the pod, no more.
        The JSON object formatted EXACTLY as outlined above.
        """
        
        # Safely format the prompt with variables
        formatted_prompt = prompt_template.format(pod_name=pod_name, namespace=namespace)
        print("✅ Prompt built successfully")
        print(f"Prompt length: {len(formatted_prompt)} characters")
        
        user_prompts = [formatted_prompt]
        
    * The agent then uses the prompt to call the model which is supposed to get the failing pod logs via the openshift tool, then search the web via the tavily tool if available for a solution and finally opens an issue on the Gitea repository that the tool has access to with the information from the web search - and if that failed with the contents of the pod log.
    