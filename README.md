# Cilium + Istio Ambient Mode Lab

A demonstration project showing how Cilium network policies and Istio ambient service mesh work together to provide defense-in-depth security for Kubernetes workloads.

## Architecture Overview

This lab deploys a simple 3-tier application:
- **hello-gateway**: Istio ingress gateway (Kubernetes Gateway API)
- **hello-app**: Python Flask application that queries PostgreSQL and external APIs
- **postgres**: PostgreSQL 17 database

### Technology Stack

- **Kubernetes**: kind cluster (local development)
- **Cilium**: CNI providing L3/L4/L7 network policy enforcement
- **Istio Ambient Mode**: Service mesh without sidecars, providing mTLS and identity-based policies
- **ztunnel**: Istio's L4 proxy (DaemonSet) that handles transparent mTLS encryption

## Traffic Flow and Encryption

### Request Path: External → Gateway → hello-app → postgres

```
External Client
    ↓ (HTTP plaintext)
hello-gateway pod
    ↓ (app sends to hello-app:8000)
ztunnel (node-local)
    ↓ (mTLS encrypted, SPIFFE identity attached)
Network
    ↓ (mTLS encrypted tunnel)
ztunnel (destination node)
    ↓ (mTLS decrypted)
hello-app pod
    ↓ (app sends to postgres:5432)
ztunnel (node-local)
    ↓ (mTLS encrypted)
Network
    ↓ (mTLS encrypted tunnel)
ztunnel (destination node)
    ↓ (mTLS decrypted)
postgres pod
```

### How Istio Ambient Mode Works

Unlike traditional Istio with sidecar proxies, ambient mode uses a **shared node-local proxy** (ztunnel):

1. **Traffic Redirection**: iptables rules redirect pod traffic to ztunnel on the same node
2. **Identity Injection**: ztunnel reads the pod's ServiceAccount and injects SPIFFE identity
3. **mTLS Encryption**: ztunnel encrypts traffic with mTLS before sending to network
4. **Policy Enforcement**: ztunnel enforces Istio AuthorizationPolicy based on identity
5. **Transparent**: Pods are unaware of mTLS - no code changes or sidecar required

### mTLS Certificate Details

- **Issuer**: istiod (Istio control plane CA)
- **Identity Format**: `spiffe://cluster.local/ns/<namespace>/sa/<serviceaccount>`
- **Lifetime**: 24 hours (default)
- **Rotation**: Automatic at 50% lifetime (12 hours)
- **Storage**: Private keys stored in ztunnel memory, never written to disk
- **Validation**: Peer certificates validated on every connection

Example identities in this lab:
- Gateway: `spiffe://cluster.local/ns/demo/sa/hello-gateway-istio`
- hello-app: `spiffe://cluster.local/ns/demo/sa/hello-app`
- postgres: `spiffe://cluster.local/ns/demo/sa/postgres`

## Identity and Authorization

### Istio Identity (SPIFFE)

Every workload gets a cryptographic identity based on its Kubernetes ServiceAccount:

```yaml
# ServiceAccount defines the identity
apiVersion: v1
kind: ServiceAccount
metadata:
  name: hello-app
  namespace: demo

# Istio automatically issues a certificate with identity:
# spiffe://cluster.local/ns/demo/sa/hello-app
```

### Istio AuthorizationPolicy (L4 Identity-Based)

Enforces **WHO** can access **WHAT** based on cryptographic identity:

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: hello-app-policy
  namespace: demo
spec:
  selector:
    matchLabels:
      app: hello-app
  action: ALLOW
  rules:
    - from:
        - source:
            principals:
              - cluster.local/ns/demo/sa/hello-gateway-istio
      to:
        - operation:
            ports:
              - "8000"
```

This policy says:
- **Only** the gateway (with identity `cluster.local/ns/demo/sa/hello-gateway-istio`) can access hello-app
- Access is **only** allowed on port 8000
- All other traffic is **denied by default**

### Istio PeerAuthentication (mTLS Enforcement)

Enforces that **ALL** communication uses mTLS:

```yaml
apiVersion: security.istio.io/v1
kind: PeerAuthentication
metadata:
  name: default
  namespace: demo
spec:
  mtls:
    mode: STRICT
```

- **STRICT**: Only accept mTLS connections (reject plaintext)
- **PERMISSIVE**: Accept both mTLS and plaintext (for migration)
- This lab uses **STRICT** for zero-trust security

## Network Policy with Cilium

### Defense in Depth: Cilium + Istio

Both Cilium and Istio enforce policies, providing **layered security**:

| Layer | Technology | What It Enforces | Policy Type |
|-------|-----------|------------------|-------------|
| L3/L4 Network | Cilium | IP addresses, ports, protocols | CiliumNetworkPolicy |
| L4/L7 Identity | Istio | Workload identity, HTTP paths | AuthorizationPolicy |
| Encryption | Istio | mTLS for all communication | PeerAuthentication |

**Both layers must allow traffic** for a connection to succeed.

### Cilium NetworkPolicy Structure

```
cilium-network-policies/
├── 00-base.yaml           # Default deny + DNS
├── 01-istio-ambient.yaml  # HBONE (ztunnel communication)
├── 02-hello-app.yaml      # hello-app specific policies
├── 03-postgres.yaml       # postgres specific policies
├── 04-gateway.yaml        # gateway specific policies
└── 05-observability.yaml  # Prometheus metrics scraping
```

### Example: L7 SNI Filtering with Cilium

Cilium can enforce L7 policies even with mTLS traffic by inspecting the SNI (Server Name Indication) field:

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: hello-app-to-github
  namespace: demo
spec:
  endpointSelector:
    matchLabels:
      app: hello-app
  egress:
    - toEntities:
        - world
      toPorts:
        - ports:
            - port: "443"
              protocol: TCP
          serverNames:
            - "api.github.com"  # ALLOWED
            # api.cloudflare.com would be BLOCKED
```

This works because:
1. SNI is sent in plaintext during TLS handshake (before encryption)
2. Cilium's eBPF programs can inspect SNI before connection is established
3. Only connections to `api.github.com` are allowed; others are dropped

### DNS Policy Considerations in Ambient Mode

**Important**: DNS policy in the `demo` namespace cannot effectively restrict DNS destinations due to Istio ambient architecture:

1. Pods in `demo` namespace have Cilium policies applied
2. All traffic is redirected through **ztunnel** (in `istio-system` namespace)
3. ztunnel has **no policy enforcement** (Cilium policies disabled)
4. ztunnel makes DNS queries on behalf of pods
5. Therefore, DNS can reach any destination regardless of `demo` namespace policy

To truly restrict DNS:
- Apply Cilium policies to ztunnel in `istio-system` namespace, **OR**
- Use Cilium DNS proxy with L7 visibility, **OR**
- Use Istio ServiceEntry resources to control external service access

The current `allow-dns` policy is **honest** - it allows DNS without claiming to restrict destinations.

## Policy Enforcement Points

### Where Policies Are Enforced

```
Pod (hello-app)
    ↓
[Cilium eBPF] ← CiliumNetworkPolicy enforcement (L3/L4/L7 network)
    ↓
iptables redirect
    ↓
ztunnel
    ↓
[Istio Policy] ← AuthorizationPolicy enforcement (L4 identity-based)
    ↓
[mTLS Encryption] ← PeerAuthentication enforcement (STRICT mode)
    ↓
Network
```

**Cilium enforces**: Source/destination IP, ports, protocols, SNI (L7)
**Istio enforces**: Source/destination identity (SPIFFE), mTLS requirement

### Policy Evaluation Order

1. **Cilium NetworkPolicy** evaluated first (eBPF at network interface)
   - If blocked: packet dropped, connection fails
   - If allowed: proceeds to next layer

2. **iptables redirect** to ztunnel (transparent to pod)

3. **Istio AuthorizationPolicy** evaluated by ztunnel
   - If no ALLOW rule matches: connection rejected (default deny)
   - If ALLOW rule matches: proceeds to mTLS

4. **Istio PeerAuthentication** enforced by ztunnel
   - If STRICT mode and peer doesn't present valid mTLS cert: connection rejected
   - If valid mTLS cert: connection established

## Security Model

### Security Layers Visualization

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                        │
│              (hello-app, postgres, gateway)                  │
└─────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────┐
│                  Istio AuthorizationPolicy                   │
│              (Identity-based L4/L7 enforcement)              │
│   • Validates SPIFFE identity from mTLS certificate          │
│   • cluster.local/ns/demo/sa/hello-app                       │
│   • Default DENY, explicit ALLOW rules required              │
└─────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────┐
│               Istio PeerAuthentication (mTLS)                │
│                (Encryption & Identity Transport)             │
│   • STRICT mode - reject plaintext connections               │
│   • Certificates issued by istiod CA                         │
│   • Auto-rotation every 12 hours (24h lifetime)              │
└─────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────┐
│                 ztunnel (L4 Proxy Layer)                     │
│           (Transparent mTLS Encryption/Decryption)           │
│   • DaemonSet - one per node                                 │
│   • Enforces AuthorizationPolicy                             │
│   • Handles certificate management                           │
│   • Port 15001 (outbound), 15006 (inbound), 15008 (HBONE)   │
└─────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────┐
│              Cilium NetworkPolicy (eBPF Layer)               │
│              (L3/L4/L7 Network-level enforcement)            │
│   • IP address, port, protocol filtering                     │
│   • SNI-based L7 HTTPS filtering                             │
│   • DNS policy (with caveats in ambient mode)                │
│   • toEntities: world, cluster, host                         │
└─────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────┐
│                    Network Infrastructure                     │
│                  (Physical/Virtual Network)                  │
└─────────────────────────────────────────────────────────────┘
```

### Zero-Trust Principles

1. **Default Deny**: Both Cilium and Istio default to denying all traffic
2. **Least Privilege**: Each workload gets only the minimum required permissions
3. **Identity-Based**: Authorization based on cryptographic identity, not IP
4. **Defense in Depth**: Multiple layers of security (network + identity + encryption)
5. **Encrypted Communication**: All workload-to-workload traffic uses mTLS

### What Each Layer Protects Against

**Cilium NetworkPolicy**:
- Network-level attacks (port scanning, network pivoting)
- Exfiltration via unexpected ports or protocols
- Access to unauthorized network destinations
- DNS tunneling (with proper ztunnel policies)

**Istio AuthorizationPolicy**:
- Lateral movement (compromised workload accessing other services)
- Identity spoofing (attacker must have valid mTLS certificate)
- Unauthorized access (even if network policy allows, identity policy can deny)

**Istio PeerAuthentication**:
- Man-in-the-middle attacks (mTLS provides confidentiality and integrity)
- Eavesdropping (all traffic encrypted)
- Plaintext protocol attacks (STRICT mode rejects non-mTLS)

## Setup Instructions

### Prerequisites

- Docker
- kind (Kubernetes v1.34.0)
- kubectl
- helm
- cilium CLI (v0.18.9)
- istioctl (v1.28.1)

### 1. Create kind Cluster

```bash
kind create cluster --name ebpf-lab --config kind-config.yaml
```

This creates a 2-node cluster with disabled default CNI.

### 2. Install Cilium

```bash
cilium install --version 1.18.3
cilium status --wait
```

Cilium becomes the CNI and handles pod networking.

**Installed version**: Cilium 1.18.3

### 3. Install Istio Ambient Mode

```bash
istioctl install --set profile=ambient -y
```

This installs:
- istiod (control plane)
- ztunnel (DaemonSet on each node)
- CNI plugin (for traffic redirection)

**Installed version**: Istio 1.28.1

### 4. Enable Ambient Mode for demo Namespace

```bash
kubectl create namespace demo
kubectl label namespace demo istio.io/dataplane-mode=ambient
```

All pods in this namespace will automatically use ztunnel for mTLS.

### 5. Deploy Application

```bash
# Build application image (if not already built)
docker build -t hello-db-app:latest ./app
kind load docker-image hello-db-app:latest --name ebpf-lab

# Deploy postgres and hello-app
kubectl apply -f pg.yaml
kubectl apply -f hello-app.yaml

# Deploy gateway
kubectl apply -f hello-gateway.yaml

# Apply Istio policies
kubectl apply -f peer-authentication.yaml
kubectl apply -f hello-policy-l4.yaml
```

### 6. Apply Cilium Network Policies

```bash
kubectl apply -f cilium-network-policies/
```

Apply policies in order:
1. Base policies (default deny + DNS)
2. Istio ambient policies (HBONE)
3. Workload-specific policies
4. Gateway policies
5. Observability policies

### 7. Verify Installation

```bash
# Check Cilium policy enforcement
kubectl get ciliumnetworkpolicies -n demo

# Check Istio policies
kubectl get peerauthentication,authorizationpolicy -n demo

# Check workload status
kubectl get pods -n demo

# Verify mTLS
istioctl x describe pod <pod-name> -n demo
```

## Testing

### Access the Application

```bash
# Get gateway external IP (for LoadBalancer) or use port-forward
kubectl port-forward -n demo svc/hello-gateway-istio 8080:80

# Access application
curl http://localhost:8080/
curl http://localhost:8080/health
curl http://localhost:8080/github
```

### Verify mTLS

```bash
# Check mTLS status
istioctl x describe pod -n demo $(kubectl get pod -n demo -l app=hello-app -o jsonpath='{.items[0].metadata.name}')

# View certificates
kubectl exec -n istio-system ds/ztunnel -- curl -s localhost:15000/certs
```

### Test Policy Enforcement

```bash
# Deploy a test pod without proper identity
kubectl run -n demo test --image=curlimages/curl --rm -it -- /bin/sh

# Try to access hello-app (should fail - no matching AuthorizationPolicy)
curl hello-app:8000

# Try to access postgres (should fail - blocked by both Cilium and Istio)
curl postgres:5432
```

### Verify Cilium Policy

```bash
# Get endpoint ID for hello-app pod
kubectl get ciliumendpoints -n demo

# View applied policies
cilium policy get <endpoint-id>

# Monitor policy decisions
cilium monitor --type policy-verdict
```

## Observability

### Cilium

```bash
# Hubble (Cilium's network observability)
cilium hubble enable
cilium hubble ui

# View network flows
hubble observe -n demo --follow
```

### Istio

```bash
# Prometheus (if installed)
kubectl port-forward -n istio-system svc/prometheus 9090:9090

# Grafana (if installed)
kubectl port-forward -n istio-system svc/grafana 3000:3000

# View ztunnel logs
kubectl logs -n istio-system -l app=ztunnel --tail=100 -f
```

## Troubleshooting

### Connection Failures

If connections fail, check each layer:

1. **Cilium NetworkPolicy**:
   ```bash
   cilium monitor --type drop -n demo
   kubectl get ciliumnetworkpolicies -n demo
   ```

2. **Istio AuthorizationPolicy**:
   ```bash
   kubectl logs -n istio-system -l app=ztunnel | grep -i denied
   kubectl get authorizationpolicy -n demo -o yaml
   ```

3. **mTLS Issues**:
   ```bash
   istioctl x describe pod <pod-name> -n demo
   kubectl logs -n istio-system -l app=istiod | grep -i certificate
   ```

### Health Check Issues in Ambient Mode

Kubelet health probes bypass ztunnel and appear as `world` entity in Cilium policies. Ensure health check policies allow `fromEntities: [world]`.

### DNS Issues

If DNS resolution fails, ensure:
- `allow-dns` policy is applied in demo namespace
- Pods can reach ztunnel (HBONE policies applied)
- ztunnel can reach kube-dns (no restrictive policies on istio-system)

## Key Differences: Istio Ambient vs Sidecar

| Aspect | Ambient Mode (ztunnel) | Sidecar Mode |
|--------|----------------------|--------------|
| **Deployment** | DaemonSet (one per node) | Container in each pod |
| **Resource Usage** | Shared, lower overhead | Per-pod overhead |
| **Latency** | Lower (no extra hop) | Higher (intra-pod hop) |
| **L7 Features** | Requires waypoint proxy | Built-in to sidecar |
| **mTLS** | ✅ Full support | ✅ Full support |
| **Identity** | ✅ ServiceAccount-based | ✅ ServiceAccount-based |
| **Policy** | L4 by default, L7 with waypoint | L7 by default |
| **Upgrades** | Rolling update DaemonSet | Restart all pods |

## Security Best Practices

1. **Always use STRICT mTLS** in production (via PeerAuthentication)
2. **Apply both Cilium and Istio policies** for defense in depth
3. **Use dedicated ServiceAccounts** for each workload
4. **Default deny all traffic**, then explicitly allow required paths
5. **Limit external egress** using Cilium's `toEntities` and SNI filtering
6. **Rotate secrets regularly** (database passwords, API keys)
7. **Monitor policy violations** using Cilium Hubble and Istio metrics
8. **Test policy changes** in non-production environments first
9. **Document exceptions** when policies must be relaxed
10. **Regular security audits** of all policies

## Contributing

This is a demo/lab project. Contributions welcome for:
- Additional security scenarios
- More complex traffic patterns
- Alternative deployment methods
- Documentation improvements

## License

MIT License - use freely for learning and demonstration purposes.

## Common Scenarios and Examples

### Scenario 1: Allow Access to New External API

**Requirement**: hello-app needs to access `api.example.com` on HTTPS.

**Solution**: Add Cilium NetworkPolicy with SNI filtering:

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: hello-app-to-example-api
  namespace: demo
spec:
  endpointSelector:
    matchLabels:
      app: hello-app
  egress:
    - toEntities:
        - world
      toPorts:
        - ports:
            - port: "443"
              protocol: TCP
          serverNames:
            - "api.example.com"
```

### Scenario 2: New Workload Needs Database Access

**Requirement**: Deploy `worker-app` that needs to query postgres.

**Steps**:

1. Create ServiceAccount for identity:
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: worker-app
  namespace: demo
```

2. Add Istio AuthorizationPolicy to postgres:
```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: postgres-policy
  namespace: demo
spec:
  selector:
    matchLabels:
      app: postgres
  action: ALLOW
  rules:
    - from:
        - source:
            principals:
              - cluster.local/ns/demo/sa/hello-app
              - cluster.local/ns/demo/sa/worker-app  # Add this
      to:
        - operation:
            ports:
              - "5432"
```

3. Add Cilium NetworkPolicy:
```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: worker-app-to-postgres
  namespace: demo
spec:
  endpointSelector:
    matchLabels:
      app: worker-app
  egress:
    - toEndpoints:
        - matchLabels:
            app: postgres
      toPorts:
        - ports:
            - port: "5432"
              protocol: TCP
```

### Scenario 3: Debugging Connection Failures

**Problem**: New workload can't connect to existing service.

**Debugging Steps**:

1. Check Cilium policy drops:
```bash
kubectl exec -n kube-system ds/cilium -- cilium-dbg monitor --type drop
```

2. Check Istio policy denials:
```bash
kubectl logs -n istio-system -l app=ztunnel | grep -i "denied\|rejected"
```

3. Verify identity:
```bash
istioctl x describe pod <pod-name> -n demo
```

4. Check endpoint policies:
```bash
kubectl get ciliumendpoints -n demo <pod-name> -o yaml
```

### Scenario 4: Restrict Outbound to Specific IP Range

**Requirement**: Only allow hello-app to access `10.0.0.0/8` range externally.

**Solution**: Use Cilium CIDR-based policy:

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: hello-app-cidr-egress
  namespace: demo
spec:
  endpointSelector:
    matchLabels:
      app: hello-app
  egress:
    - toCIDR:
        - 10.0.0.0/8
      toPorts:
        - ports:
            - port: "443"
              protocol: TCP
```

### Scenario 5: Enable L7 HTTP Policies with Waypoint

**Requirement**: Enforce HTTP method and path-based policies.

**Solution**: Deploy waypoint proxy for L7 capabilities:

```bash
# Create waypoint for demo namespace
istioctl x waypoint apply --namespace demo

# Add L7 AuthorizationPolicy
kubectl apply -f - <<EOF
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: hello-app-l7-policy
  namespace: demo
spec:
  selector:
    matchLabels:
      app: hello-app
  action: ALLOW
  rules:
    - from:
        - source:
            principals:
              - cluster.local/ns/demo/sa/hello-gateway-istio
      to:
        - operation:
            methods: ["GET", "POST"]
            paths: ["/", "/health", "/github"]
EOF
```

## References

- [Cilium Documentation](https://docs.cilium.io/)
- [Istio Ambient Mode](https://istio.io/latest/docs/ambient/)
- [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/)
- [SPIFFE Identity](https://spiffe.io/)
- [eBPF](https://ebpf.io/)
