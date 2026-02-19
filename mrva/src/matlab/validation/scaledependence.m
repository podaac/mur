

scales=1:12;


L=scales;

      gridgrain=45./(2.^L);  % degrees.

      rho=0.8*exp( -(45./(2.^L))/4.0 );


plot(L,gridgrain,L,rho);

