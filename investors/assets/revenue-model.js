/* Planning assumptions, not actual performance. Month 1 = commercial launch. */
const RevenueModel = (() => {
  const prices = Object.freeze({ registration:1999, firstFee:499, repeatFee:249, cover:500, guruIntro:99, guru:199, setup:0 });
  const cases = Object.freeze({
    Cautious:{paidTarget:450,meta:100000,provider:80000,productCost:150000,spend:180000,activeMonths:3,firstDate:.30,repeatRate:.20,guruAdoption:.10},
    Base:{paidTarget:900,meta:125000,provider:180000,productCost:250000,spend:305000,activeMonths:6,firstDate:.50,repeatRate:.35,guruAdoption:.20},
    Upside:{paidTarget:1500,meta:150000,provider:300000,productCost:400000,spend:450000,activeMonths:9,firstDate:.70,repeatRate:.50,guruAdoption:.30}
  });
  function calculate(name, options={}) {
    const c={...cases[name],...options};
    if(!cases[name]) throw new Error('Unknown scenario');
    const cohorts=[]; let cumulativeSignups=0,cumulativePaid=0,cumulativeBgv=0,marketing=prices.setup;
    let cumulativeFees=0, cumulativeCollections=0, cumulativeCover=0, cumulativeOperations=0;
    return Array.from({length:60},(_,i)=>{
      const month=i+1, spend=c.meta+c.provider,paid=c.paidTarget,signups=null;
      cohorts.push(paid); const active=cohorts.slice(-c.activeMonths).reduce((a,b)=>a+b,0);
      cumulativePaid+=paid;marketing+=spend;
      // Each converted cohort has first dates in its joining month. Repeat participants
      // come only from prior first-date cohorts, until the assumed activity window ends.
      const firstParticipants=paid*c.firstDate;
      const repeatParticipants=(active-paid)*c.firstDate*c.repeatRate;
      const participants=firstParticipants+repeatParticipants;
      const guruSubscribers=month>=7?active*c.guruAdoption:0;
      const guruPrice=month<7?0:month<=12?prices.guruIntro:prices.guru;
      const registration=paid*prices.registration;
      const dates=firstParticipants*prices.firstFee+repeatParticipants*prices.repeatFee;
      const guru=guruSubscribers*guruPrice;
      const fees=registration+dates+guru, cover=participants*prices.cover;
      const bgv=paid*150, operations=0; cumulativeOperations+=operations;cumulativeBgv+=bgv;
      cumulativeFees+=fees; cumulativeCover+=cover; cumulativeCollections+=fees+cover;
      return {month,signups,paid,active,firstParticipants,repeatParticipants,participants,
        pairDates:participants/2,guruSubscribers,registration,dates,guru,fees,cover,
        productCost:c.productCost,cumulativeProduct:c.productCost*month,net:cumulativeFees-cumulativeBgv-marketing-c.productCost*month,bgv,operations,cumulativeBgv,cumulativeOperations,collections:fees+cover,cumulativeFees,cumulativeCover,cumulativeCollections,
        cumulativeSignups,cumulativePaid,
        marketing,paidCAC:paid?spend/paid:0};
    });
  }
  return {prices,cases,calculate};
})();
if(typeof module!=='undefined') module.exports=RevenueModel;
