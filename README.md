 Issue Resolved!

  The Istio ambient installation is now working correctly. Here's what was fixed:

  Root Cause

  Cilium was configured with cni-exclusive: true, which prevented Istio CNI from coexisting. Cilium kept reverting any CNI configuration changes that Istio tried to make.

  Fix Applied

  1. ✅ Patched Cilium ConfigMap: cni-exclusive: false
  2. ✅ Restarted Cilium pods to apply the configuration
  3. ✅ Verified Istio CNI pods are now Ready (1/1)

  Current Status

  istio-system pods:
  ✓ istio-cni-node-c7jgm    1/1  Running
  ✓ istio-cni-node-s6grs    1/1  Running
  ✓ istiod-5f546f645c-5r6lf 1/1  Running
  ✓ ztunnel-pdxpv           1/1  Running
  ✓ ztunnel-xtscb           1/1  Running

  Next Steps

  You can now:
  1. Deploy workloads with ambient mesh enabled
  2. Verify the ambient mesh is working by checking ztunnel logs
  3. Test L4 authorization policies

  The Istio ambient installation should now be complete. If you want to test it, you can deploy a sample application and verify the ambient mesh captures traffic through ztunnel.
