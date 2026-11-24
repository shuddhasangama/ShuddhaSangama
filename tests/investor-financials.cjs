const assert=require('node:assert/strict');
const model=require('../investors/assets/revenue-model.js');
// Independent control totals from the approved 24-Nov funding workbook.
const controls={
 Conservative:[6000,5830046.235799718,8302525.264200282,6275292.117763428,944582.928964482],
 Base:[12000,9670092.471599435,18095050.528400563,14362402.417345036,1139165.8579289645],
 Aggressive:[18000,14341956.889217336,27055757.610782664,21381785.444199372,1646625]
};
for(const [name,expected]of Object.entries(controls)){
 const months=model.calculate(name),r=months[11];
 [r.paidTotal,r.costs,r.cash,r.headroom,r.reserveGap].forEach((v,i)=>assert(Math.abs(v-expected[i])<.01,`${name} metric ${i}`));
 assert.equal(months.length,12);assert.equal(months[0].cities,3);assert.equal(r.cities,11);
 assert.equal(months[0].date,0);assert.equal(months[1].repeat,0);
 assert.equal(months[1].first,months[0].paid*.6);
 assert.equal(months[2].repeat,months[1].first*.1);
 assert(months.slice(0,3).every(m=>m.cities===3));
 assert.equal(months[3].cities,4);
 const firstTotal=months.slice(0,11).reduce((sum,m)=>sum+m.paid,0)*.6;
 assert(Math.abs(months.reduce((sum,m)=>sum+m.first,0)-firstTotal)<.001);
 assert.equal(model.calculate(name,{firstDate:0})[11].dateTotal,0);
 assert(Math.abs(r.collections-r.registrationTotal-r.dateTotal)<.001);
 let cash=500000;
 for(const row of months){cash+=row.revenue-row.cost;assert(Math.abs(cash-row.cash)<.01);assert.equal(row.paidTotal,months.slice(0,row.month).reduce((s,m)=>s+m.paid,0));assert(Math.abs(row.headroom-row.productAllocation-row.marketingAllocation-row.regionAllocation)<.01);}
 assert(Math.abs(r.collections-r.costs+500000-r.cash)<.01);
}
assert.throws(()=>model.calculate('Unknown'));
console.log('PASS: all three website scenarios reconcile to the funding workbook; cash and allocations balance.');
