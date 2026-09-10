function toggleProviderFields(){const role=document.getElementById('role');const fields=document.getElementById('providerFields');if(role&&fields)fields.style.display=role.value==='provider'?'block':'none';}
document.addEventListener('DOMContentLoaded',toggleProviderFields);
