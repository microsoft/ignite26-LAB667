# Configure Model Access

Your goal is to connect the player project to an available Azure OpenAI model deployment in Microsoft Foundry. This matters because the player and its specialists need a working model client before they can reason about missions or choose tools.

## Challenge

Identify the endpoint and deployment name supplied for the workshop, authenticate without embedding secrets in code, and make those values available to the player through **C:\workshop\\.env**.

## Expected outcome

- The project can create its model client from environment configuration.
- The endpoint and deployment name target the intended workshop resource.
- Authentication uses the provided lab identity or approved credential flow.
- Missing or invalid model configuration fails clearly.

## Completion check

A minimal model request succeeds from the workshop environment, and no model credentials appear in tracked source files.
