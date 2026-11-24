import json,sys
s=json.load(open('results/summary.json'))
for n,r in s.items():
  if 'far' in r:
    f,ne=r['far'],r['near']
    print('%-30s rb=%2.0f cap=%4.1fp | near: tr=%4.0f tf=%4.0f EH=%4.0f J=%4.0f K=%5.0f jit=%3.0f | far: tr=%4.0f EH=%4.0f jit=%3.0f dly=%.2f'%(n,r.get('rbase',0),r['tx_cap_pF'],ne['rise_ps'] or 0,ne['fall_ps'] or 0,ne['eye_height_mV'],ne['vJ_mV'],ne['vK_mV'],ne['jitter_pp_ps'],f['rise_ps'] or 0,f['eye_height_mV'],f['jitter_pp_ps'],f['delay_ns']))
  elif n!='trim': print('%-30s %s'%(n,{k:(round(v,3) if isinstance(v,float) else v) for k,v in r.items()}))
  else: print('trim', {k:v for k,v in r.items() if not isinstance(v,list)})
