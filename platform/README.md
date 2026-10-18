# platform

ArgoCD app-of-apps and Helm values for everything running in the cluster.

- Part A: k3d in WSL, using the local values files.
- Part B: k3s on AWS, using `values-aws` overrides.
- Every workload sets memory requests and limits (WSL has 10GB in total).
