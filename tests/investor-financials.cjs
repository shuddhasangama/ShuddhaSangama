const assert=require('node:assert/strict');
const model=require('../investors/assets/revenue-model.js');
// Independent control totals from the approved 24-Nov funding workbook.
const controls={
 Conservative:[6000,5751454.545454545,6742545.454545455,4755836.363636364,976400],
 Base:[12000,9512909.090909092,14975090.909090908,11323490.909090908,1175800],
 Aggressive:[18000,14106181.818181818,22375818.18181818,16823418.18181818,1646625]
};
for(const [name,expected]of Object.entries(controls)){
 const months=model.calculate(name),r=months[11];
 [r.paidTotal,r.costs,r.cash,r.headroom,r.reserveGap].forEach((v,i)=>assert(Math.abs(v-expected[i])<.01,`${name} metric ${i}`));
 assert.equal(months.length,12);assert.equal(months[0].cities,3);assert.equal(r.cities,11);
 let cash=500000;
 for(const row of months){cash+=row.revenue-row.cost;assert(Math.abs(cash-row.cash)<.01);assert.equal(row.paidTotal,months.slice(0,row.month).reduce((s,m)=>s+m.paid,0));assert(Math.abs(row.headroom-row.productAllocation-row.marketingAllocation-row.regionAllocation)<.01);}
 assert(Math.abs(r.collections-r.costs+500000-r.cash)<.01);
}
assert.throws(()=>model.calculate('Unknown'));
console.log('PASS: all three website scenarios reconcile to the funding workbook; cash and allocations balance.');
