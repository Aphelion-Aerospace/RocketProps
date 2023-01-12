# -*- coding: utf-8 -*-
r'''Chemical Engineering Design Library (ChEDL). Utilities for process modeling.
Copyright (C) 2016, 2017, 2018, 2019, 2020 Caleb Bell <Caleb.Andrew.Bell@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

This module contains implementations of  Peng-Robinson

Standard Peng-Robinson Family EOSs
==================================

Standard Peng Robinson
----------------------
.. autoclass:: PR
   :show-inheritance:
   :members: a_alpha_pure, a_alpha_and_derivatives_pure, d3a_alpha_dT3_pure,
             solve_T, P_max_at_V, c1, c2, Zc

Ideal Gas Equation of State
===========================
.. autoclass:: IG
   :show-inheritance:
   :members: volume_solutions, Zc, a, b, delta, epsilon, a_alpha_pure, a_alpha_and_derivatives_pure, solve_T

'''

from math import sqrt, log
from cmath import  atanh as catanh

k = 1.380649e-23
N_A = 6.02214076e23
R  = N_A*k # 8.31446261815324 exactly now, N_A*k
is_micropython = False


R2 = R*R
R_2 = 0.5*R
R_inv = 1.0/R
R_inv2 = R_inv*R_inv

def deflate_cubic_real_roots(b, c, d, x0):
    F = b + x0
    G = -d/x0

    D = F*F - 4.0*G
#     if D < 0.0:
#         D = (-D)**0.5
#         x1 = (-F + D*1.0j)*0.5
#         x2 = (-F - D*1.0j)*0.5
#     else:
    if D < 0.0:
        return (0.0, 0.0)
    D = sqrt(D)
    x1 = 0.5*(D - F)#(D - c)*0.5
    x2 = 0.5*(-F - D) #-(c + D)*0.5
    return x1, x2


def volume_solutions_halley(T, P, b, delta, epsilon, a_alpha):
    r'''Halley's method based solver for cubic EOS volumes based on the idea
    of initializing from a single liquid-like guess which is solved precisely,
    deflating the cubic analytically, solving the quadratic equation for the
    next two volumes, and then performing two halley steps on each of them
    to obtain the final solutions. This method does not calculate imaginary
    roots - they are set to zero on detection. This method has been rigorously
    tested over a wide range of conditions.
    
    The method uses the standard combination of bisection to provide high
    and low boundaries as well, to keep the iteration always moving forward.

    Parameters
    ----------
    T : float
        Temperature, [K]
    P : float
        Pressure, [Pa]
    b : float
        Coefficient calculated by EOS-specific method, [m^3/mol]
    delta : float
        Coefficient calculated by EOS-specific method, [m^3/mol]
    epsilon : float
        Coefficient calculated by EOS-specific method, [m^6/mol^2]
    a_alpha : float
        Coefficient calculated by EOS-specific method, [J^2/mol^2/Pa]

    Returns
    -------
    Vs : tuple[float]
        Three possible molar volumes, [m^3/mol]

    Notes
    -----
    A sample region where this method works perfectly is shown below:

    .. figure:: eos/volume_error_halley_PR_methanol_low.png
       :scale: 70 %
       :alt: PR EOS methanol volume error low pressure

    '''
    '''
    Cases known to be failing:
    '''
    # Test the case where a_alpha is so low, even with the lowest possible volume `b`,
    # the value of the second term plus P is equal to P.
    if a_alpha/(b*(b + delta) + epsilon) + P == P:
        return (b + R*T/P, 0.0, 0.0)
    # Run this first, before the low P criteria
    if a_alpha > 1e4:
        V_possible = high_alpha_one_root(T, P, b, delta, epsilon, a_alpha)
        if V_possible != 0.0:
            return (V_possible, 0.0, 0.0)
    RT = R*T
    RT_2 = RT + RT
    a_alpha_2 = a_alpha + a_alpha
    P_inv = 1.0/P

    RT_inv = R_inv/T
    P_RT_inv = P*RT_inv
    B = etas = b*P_RT_inv
    deltas = delta*P_RT_inv
    thetas = a_alpha*P_RT_inv*RT_inv
    epsilons = epsilon*P_RT_inv*P_RT_inv

    b2 = (deltas - B - 1.0)
    c2 = (thetas + epsilons - deltas*(B + 1.0))
    d2 = -(epsilons*(B + 1.0) + thetas*etas)
    RT_P = RT*P_inv
    
    low_V, high_V = b*(1.0+8e-16), -RT_P*d2/c2
    if high_V <= low_V:
        high_V = b*1.000001

    V = high_V
    for j in range(50):
        x0_inv = 1.0/(V - b)
        x1_inv = 1.0/(V*(V + delta) + epsilon)
        x2 = V + V + delta
        fval = RT*x0_inv - P - a_alpha*x1_inv
        if fval < 0.0:
            high_V = V
        else:
            low_V = V
            if j == 0:
                # If we are in the first iteration we have not decided on a upper bound yet
                high_V = RT_P*10.0
                # If the ideal gas volume is in danger of being underneath the liquid volume
                # we increase it to 10b. 10 is a guess only.
                if high_V < 10.0*b:
                    high_V = 10.0*b
        x0_inv2 = x0_inv*x0_inv # make it 1/x0^2
        x1_inv2 = x1_inv*x1_inv # make it 1/x1^2
        x3 = a_alpha*x1_inv2
        fder = x2*x3 - RT*x0_inv2
        fder2 = RT_2*x0_inv2*x0_inv - a_alpha_2*x2*x2*x1_inv2*x1_inv + x3 + x3

        fder_inv = 1.0/fder
        step = fval*fder_inv
        rel_err = abs(fval*P_inv)
        step_den = 1.0 - 0.5*step*fder2*fder_inv
        if step_den != 0.0:
            # Halley's step; if step_den == 0 we do the newton step
            step = step/step_den
        V_old = V
        V_new = V - step
        # print(V, abs(1.0 - V_new/V_old), rel_err)
        if (abs(1.0 - V_new/V_old) < 6e-16
            or (j > 25 and rel_err < 1e-12)
           ):
            # One case not taken care of is oscillating behavior within the boundaries of high_V, low_V
            V = V_new
            break
        if V_new <= low_V or V_new >= high_V:
            V_new = 0.5*(low_V + high_V)
            if V_new == low_V or V_new == high_V:
                # If the bisection has finished (interval cannot be further divided)
                # the solver is finished
                break
        V = V_new
    if j != 49:
        V0 = V

        x1, x2 = deflate_cubic_real_roots(b2, c2, d2, V*P_RT_inv)
        if x1 == 0.0:
            return (V0, 0.0, 0.0)

        # If the molar volume converged on is such that the second term can be added to the
        # first term and it is still the first term, we are *extremely* ideal
        # and we should just quit
        main0 = R*T/(V - b)
        main1 = a_alpha/(V*V + delta*V + epsilon)
        # In these checks, atetmpt to evaluate if we are highly ideal
        # and there is only one solution
        if (main0 + main1 == main0) or ((main0 - main1) != 0.0 and abs(1.0-(main0 + main1)/(main0 - main1)) < 1e-12):
            return (V0, 0.0, 0.0)


        # 8 divisions only for polishing
        V1 = x1*RT_P
        V2 = x2*RT_P
#             print(V1, V2, 'deflated Vs')

        # Fixed a lot of really bad points in the plots with these.
        # Article suggests they are not needed, but 1 is better than 11 iterations!
        # These loops do need to be converted into a tight conditional functional test
        if P < 1e-2:
            if x1 != 1.0:
                # we are so ideal, and we already have the liquid root - and the newton iteration overflows!
                # so we don't need to polish it if x1 is exatly 1.
                V1 = volume_solution_polish(V1, T, P, b, delta, epsilon, a_alpha)
            V2 = volume_solution_polish(V2, T, P, b, delta, epsilon, a_alpha)
        else:
            V = V1
            t90 = V*(V + delta) + epsilon
            if t90 != 0.0:
                x0_inv = 1.0/(V - b)
                x1_inv = 1.0/t90
                x2 = V + V + delta
                fval = -P + RT*x0_inv - a_alpha*x1_inv
                x0_inv2 = x0_inv*x0_inv # make it 1/x0^2
                x1_inv2 = x1_inv*x1_inv # make it 1/x1^2
                x3 = a_alpha*x1_inv2
                fder = x2*x3 - RT*x0_inv2
                fder2 = RT_2*x0_inv2*x0_inv - a_alpha_2*x2*x2*x1_inv2*x1_inv + x3 + x3

                if fder != 0.0:
                    fder_inv = 1.0/fder
                    step = fval*fder_inv
                    V1 = V - step/(1.0 - 0.5*step*fder2*fder_inv)

            # Take a step with V2
            V = V2
            t90 = V*(V + delta) + epsilon
            if t90 != 0.0:
                x0_inv = 1.0/(V - b)
                x1_inv = 1.0/(t90)
                x2 = V + V + delta
                fval = -P + RT*x0_inv - a_alpha*x1_inv
                x0_inv2 = x0_inv*x0_inv # make it 1/x0^2
                x1_inv2 = x1_inv*x1_inv # make it 1/x1^2
                x3 = a_alpha*x1_inv2
                fder = x2*x3 - RT*x0_inv2
                fder2 = RT_2*x0_inv2*x0_inv - a_alpha_2*x2*x2*x1_inv2*x1_inv + x3 + x3

                if fder != 0.0:
                    fder_inv = 1.0/fder
                    step = fval*fder_inv
                    V2 = V - step/(1.0 - 0.5*step*fder2*fder_inv)
        return (V0, V1, V2)
    return (0.0, 0.0, 0.0)


def volume_solutions_NR(T, P, b, delta, epsilon, a_alpha, tries=0):
    r'''Newton-Raphson based solver for cubic EOS volumes based on the idea
    of initializing from an analytical solver. This algorithm can only be
    described as a monstrous mess. It is fairly fast for most cases, but about
    3x slower than :obj:`volume_solutions_halley`. In the worst case this
    will fall back to `mpmath`.

    Parameters
    ----------
    T : float
        Temperature, [K]
    P : float
        Pressure, [Pa]
    b : float
        Coefficient calculated by EOS-specific method, [m^3/mol]
    delta : float
        Coefficient calculated by EOS-specific method, [m^3/mol]
    epsilon : float
        Coefficient calculated by EOS-specific method, [m^6/mol^2]
    a_alpha : float
        Coefficient calculated by EOS-specific method, [J^2/mol^2/Pa]
    tries : int, optional
        Internal parameter as this function will call itself if it needs to;
        number of previous solve attempts, [-]

    Returns
    -------
    Vs : tuple[complex]
        Three possible molar volumes, [m^3/mol]

    Notes
    -----

    Sample regions where this method works perfectly are shown below:

    .. figure:: eos/volume_error_NR_PR_methanol_high.png
       :scale: 70 %
       :alt: PR EOS methanol volume error high pressure

    .. figure:: eos/volume_error_NR_PR_methanol_low.png
       :scale: 70 %
       :alt: PR EOS methanol volume error low pressure

    '''


    '''Even if mpmath is used for greater precision in the calculated root,
    it gets rounded back to a float - and then error occurs.
    Cannot beat numerical method or numpy roots!

    The only way out is to keep volume as many decimals, to pass back in
    to initialize the TV state.
    '''
    # Initial calculation - could use any method, however this is fastest
    # 2 divisions, 2 powers in here
    # First bit is top left corner
    if a_alpha == 0.0:
        '''from sympy import *
            R, T, P, b, V = symbols('R, T, P, b, V')
            solve(Eq(P, R*T/(V-b)), V)
        '''
        # EOS has devolved into having the first term solution only
        return [b + R*T/P, -1j, -1j]
    if P < 1e-2:
    # if 0 or (0 and ((T < 1e-2 and P > 1e6) or (P < 1e-3 and T < 1e-2) or (P < 1e-1 and T < 1e-4) or P < 1)):
        # Not perfect but so much wasted dev time need to move on, try other fluids and move this tolerance up if needed
        # if P < min(GCEOS.P_discriminant_zeros_analytical(T=T, b=b, delta=delta, epsilon=epsilon, a_alpha=a_alpha, valid=True)):
            # TODO - need function that returns range two solutions are available!
            # Very important because the below strategy only works for that regime.
        if T > 1e-2 or 1:
            try:
                return volume_solutions_NR_low_P(T, P, b, delta, epsilon, a_alpha)
            except Exception as e:
                pass
#                print(e, 'was not 2 phase')

        try:
            return volume_solutions_mpmath_float(T, P, b, delta, epsilon, a_alpha)
        except:
            pass
    try:
        if tries == 0:
            Vs = list(volume_solutions_Cardano(T, P, b, delta, epsilon, a_alpha))
#                Vs = [Vi+1e-45j for Vi in volume_solutions_Cardano(T, P, b, delta, epsilon, a_alpha, quick=True)]
        elif tries == 1:
            Vs = list(volume_solutions_fast(T, P, b, delta, epsilon, a_alpha))
        elif tries == 2:
            # sometimes used successfully
            Vs = list(volume_solutions_a1(T, P, b, delta, epsilon, a_alpha))
        # elif tries == 3:
        #     # never used successfully
        #     Vs = GCEOS.volume_solutions_a2(T, P, b, delta, epsilon, a_alpha)

        # TODO fall back to tlow T
    except:
#            Vs = GCEOS.volume_solutions_Cardano(T, P, b, delta, epsilon, a_alpha)
        if tries == 0:
            Vs = list(volume_solutions_fast(T, P, b, delta, epsilon, a_alpha))
        else:
            Vs = list(volume_solutions_Cardano(T, P, b, delta, epsilon, a_alpha))
        # Zero division error is possible above

    RT = R*T
    P_inv = 1.0/P
#        maxiter = range(3)
    # The case for a fixed number of iterations has pretty much gone.
    # On 1 occasion
    failed = False
    max_err, rel_err = 0.0, 0.0
    try:
        for i in (0, 1, 2):
            V = Vi = Vs[i]
            err = 0.0
            for _ in range(11):
                # More iterations seems to create problems. No, 11 is just lucky for particular problem.
#            for _ in (0, 1, 2):
                # 3 divisions each iter = 15, triple the duration of the solve
                denom1 = 1.0/(V*(V + delta) + epsilon)
                denom0 = 1.0/(V-b)
                w0 = RT*denom0
                w1 = a_alpha*denom1
                if w0 - w1 - P == err:
                    break # No change in error
                err = w0 - w1 - P
#                print(abs(err), V, _)
                derr_dV = (V + V + delta)*w1*denom1 - w0*denom0
                V = V - err/derr_dV
                rel_err = abs(err*P_inv)
                if rel_err < 1e-14 or V == Vi:
                    # Conditional check probably not worth it
                    break
#                if _ > 5:
#                    print(_, V)
            # This check can get rid of the noise
            if rel_err > 1e-2: # originally 1e-2; 1e-5 did not change; 1e-10 to far
#            if abs(err*P_inv) > 1e-2 and (i.real != 0.0 and abs(i.imag/i.real) < 1E-10 ):
                failed = True
#                    break
            if not (.95 < (Vi/V).real < 1.05):
                # Cannot let a root become another root
                failed = True
                max_err = 1e100
                break
            Vs[i] = V
            max_err = max(max_err, rel_err)
    except:
        failed = True

#            def to_sln(V):
#                denom1 = 1.0/(V*(V + delta) + epsilon)
#                denom0 = 1.0/(V-b)
#                w0 = x2*denom0
#                w1 = a_alpha*denom1
#                err = w0 - w1 - P
##                print(err*P_inv, V)
#                return err#*P_inv
#            try:
#                from fluids.numerics import py_bisect as bisect, secant, linspace
##                Vs[i] = secant(to_sln, Vs[i].real, x1=Vs[i].real*1.0001, ytol=1e-12, damping=.6)
#                import matplotlib.pyplot as plt
#
#                plt.figure()
#                xs = linspace(Vs[i].real*.9999999999, Vs[i].real*1.0000000001, 2000000) + [Vs[i]]
#                ys = [abs(to_sln(V)) for V in xs]
#                plt.semilogy(xs, ys)
#                plt.show()
#
##                Vs[i] = bisect(to_sln, Vs[i].real*.999, Vs[i].real*1.001)
#            except Exception as e:
#                print(e)
    root_failed = not [i.real for i in Vs if i.real > b and (i.real == 0.0 or abs(i.imag/i.real) < 1E-12)]
    if not failed:
        failed = root_failed

    if failed and tries < 2:
        return volume_solutions_NR(T, P, b, delta, epsilon, a_alpha, tries=tries+1)
    elif root_failed:
#            print('%g, %g; ' %(T, P), end='')
        return volume_solutions_mpmath_float(T, P, b, delta, epsilon, a_alpha)
    elif failed and tries == 2:
        # Are we at least consistent? Diitch the NR and try to be OK with the answer
#            Vs0 = GCEOS.volume_solutions_Cardano(T, P, b, delta, epsilon, a_alpha, quick=True)
#            Vs1 = GCEOS.volume_solutions_a1(T, P, b, delta, epsilon, a_alpha, quick=True)
#            if sum(abs((i -j)/i) for i, j in zip(Vs0, Vs1)) < 1e-6:
#                return Vs0
        if max_err < 5e3:
        # if max_err < 1e6:
            # Try to catch floating point error
            return Vs
        return volume_solutions_NR_low_P(T, P, b, delta, epsilon, a_alpha)
#        print('%g, %g; ' %(T, P), end='')
#            print(T, P, b, delta, a_alpha)
#            if root_failed:
        return volume_solutions_mpmath_float(T, P, b, delta, epsilon, a_alpha)
        # return Vs
#        if tries == 3 or tries == 2:
#            print(tries)
    return Vs


def volume_solutions_mpmath(T, P, b, delta, epsilon, a_alpha, dps=50):
    r'''Solution of this form of the cubic EOS in terms of volumes, using the
    `mpmath` arbitrary precision library. The number of decimal places returned
    is controlled by the `dps` parameter.


    This function is the reference implementation which provides exactly
    correct solutions; other algorithms are compared against this one.

    Parameters
    ----------
    T : float
        Temperature, [K]
    P : float
        Pressure, [Pa]
    b : float
        Coefficient calculated by EOS-specific method, [m^3/mol]
    delta : float
        Coefficient calculated by EOS-specific method, [m^3/mol]
    epsilon : float
        Coefficient calculated by EOS-specific method, [m^6/mol^2]
    a_alpha : float
        Coefficient calculated by EOS-specific method, [J^2/mol^2/Pa]
    dps : int
        Number of decimal places in the result by `mpmath`, [-]

    Returns
    -------
    Vs : tuple[complex]
        Three possible molar volumes, [m^3/mol]

    Notes
    -----
    Although `mpmath` has a cubic solver, it has been found to fail to solve in
    some cases. Accordingly, the algorithm is as follows:

    Working precision is `dps` plus 40 digits; and if P < 1e-10 Pa, it is
    `dps` plus 400 digits. The input parameters are converted exactly to `mpf`
    objects on input.

    `polyroots` from mpmath is used with `maxsteps=2000`, and extra precision
    of 15 digits. If the solution does not converge, 20 extra digits are added
    up to 8 times. If no solution is found, mpmath's `findroot` is called on
    the pressure error function using three initial guesses from another solver.

    Needless to say, this function is quite slow.

    Examples
    --------
    Test case which presented issues for PR EOS (three roots were not being returned):

    >>> volume_solutions_mpmath(0.01, 1e-05, 2.5405184201558786e-05, 5.081036840311757e-05, -6.454233843151321e-10, 0.3872747173781095)
    (mpf('0.0000254054613415548712260258773060137'), mpf('4.66038025602155259976574392093252'), mpf('8309.80218708657190094424659859346'))

    References
    ----------
    .. [1] Johansson, Fredrik. Mpmath: A Python Library for Arbitrary-Precision
       Floating-Point Arithmetic, 2010.
    '''
    # Tried to remove some green on physical TV with more than 30, could not
    # 30 is fine, but do not dercease further!
    # No matter the precision, still cannot get better
    # Need to switch from `rindroot` to an actual cubic solution in mpmath
    # Three roots not found in some cases
    # PRMIX(T=1e-2, P=1e-5, Tcs=[126.1, 190.6], Pcs=[33.94E5, 46.04E5], omegas=[0.04, 0.011], zs=[0.5, 0.5], kijs=[[0,0],[0,0]]).volume_error()
    # Once found it possible to compute VLE down to 0.03 Tc with ~400 steps and ~500 dps.
    # need to start with a really high dps to get convergence or it is discontinuous
    if P == 0.0 or T == 0.0:
        raise ValueError("Bad P or T; issue is not the algorithm")

    import mpmath as mp
    mp.mp.dps = dps + 40#400#400
    if P < 1e-10:
        mp.mp.dps = dps + 400
    b, T, P, epsilon, delta, a_alpha = [mp.mpf(i) for i in [b, T, P, epsilon, delta, a_alpha]]
    roots = None
    if 1:
        RT_inv = 1/(mp.mpf(R)*T)
        P_RT_inv = P*RT_inv
        B = etas = b*P_RT_inv
        deltas = delta*P_RT_inv
        thetas = a_alpha*P_RT_inv*RT_inv
        epsilons = epsilon*P_RT_inv*P_RT_inv

        b = (deltas - B - 1)
        c = (thetas + epsilons - deltas*(B + 1))
        d = -(epsilons*(B + 1) + thetas*etas)

        extraprec = 15
        # extraprec alone is not enough to converge everything
        try:
            # found case 20 extrapec not enough, increased to 30
            # Found another case needing 40
            for i in range(8):
                try:
                    # Found 1 case 100 steps not enough needed 200; then found place 400 was not enough
                    roots = mp.polyroots([mp.mpf(1.0), b, c, d], extraprec=extraprec, maxsteps=2000)
                    break
                except Exception as e:
                    extraprec += 20
#                        print(e, extraprec)
                    if i == 7:
#                            print(e, 'failed')
                        raise e

            if all(i == 0 or i == 1 for i in roots):
                return volume_solutions_mpmath(T, P, b, delta, epsilon, a_alpha, dps=dps*2)
        except:
            try:
                guesses = volume_solutions_fast(T, P, b, delta, epsilon, a_alpha)
                roots = mp.polyroots([mp.mpf(1.0), b, c, d], extraprec=40, maxsteps=100, roots_init=guesses)
            except:
                pass
#            roots = np.roots([1.0, b, c, d]).tolist()
        if roots is not None:
            RT_P = mp.mpf(R)*T/P
            hits = [V*RT_P for V in roots]

    if roots is None:
#        print('trying numerical mpmath')
        guesses = volume_solutions_fast(T, P, b, delta, epsilon, a_alpha)
        RT = T*R
        def err(V):
            return(RT/(V-b) - a_alpha/(V*(V + delta) + epsilon)) - P

        hits = []
        for Vi in guesses:
            try:
                V_calc = mp.findroot(err, Vi, solver='newton')
                hits.append(V_calc)
            except Exception as e:
                pass
        if not hits:
            raise ValueError("Could not converge any mpmath volumes")
    # Return in the specified precision
    mp.mp.dps = dps
    sort_fun = lambda x: (x.real, x.imag)
    return tuple(sorted(hits, key=sort_fun))


def polyder(c, m=1, scl=1, axis=0):
    """not quite a copy of numpy's version because this was faster to
    implement."""
    cnt = m

    if cnt == 0:
        return c

    n = len(c)
    if cnt >= n:
        c = c[:1]*0
    else:
        for i in range(cnt): # normally only happens once
            n = n - 1

            der = [0.0]*n
            for j in range(n, 0, -1):
                der[j - 1] = j*c[j]
            c = der
    return c

def chebder(c, m=1, scl=1.0):
    """not quite a copy of numpy's version because this was faster to
    implement.
    
    This does not evaluate the value of a cheb series at a point; it returns
    a new chebyshev seriese to be evaluated by chebval.
    """
    c = list(c)
    cnt = int(m)
    if cnt == 0:
        return c

    n = len(c)
    if cnt >= n:
        c = []
    else:
        for i in range(cnt):
            n = n - 1
            if scl != 1.0:
                for j in range(len(c)):
                    c[j] *= scl
            der = [0.0 for _ in range(n)]
            for j in range(n, 2, -1):
                der[j - 1] = (j + j)*c[j]
                c[j - 2] += (j*c[j])/(j - 2.0)
            if n > 1:
                der[1] = 4.0*c[2]
            der[0] = c[1]
            c = der
    return c


def main_derivatives_and_departures(T, P, V, b, delta, epsilon, a_alpha,
                                    da_alpha_dT, d2a_alpha_dT2):
    epsilon2 = epsilon + epsilon
    x0 = 1.0/(V - b)
    x1 = 1.0/(V*(V + delta) + epsilon)
    x3 = R*T
    x4 = x0*x0
    x5 = V + V + delta
    x6 = x1*x1
    x7 = a_alpha*x6
    x8 = P*V
    x9 = delta*delta
    x10 = x9 - epsilon2 - epsilon2
    try:
        x11 = 1.0/sqrt(x10)
    except:
        # Needed for ideal gas model
        x11 = 0.0
    x11_half = 0.5*x11

#    arg = x11*x5
#    arg2 = (arg + 1.0)/(arg - 1.0)
#    fancy = 0.25*log(arg2*arg2)
#    x12 = 2.*x11*fancy # Possible to use a catan, but then a complex division and sq root is needed too
    x12 = 2.*x11*catanh(x11*x5).real # Possible to use a catan, but then a complex division and sq root is needed too
    x14 = 0.5*x5
    x15 = epsilon2*x11
    x16 = x11_half*x9
    x17 = x5*x6
    dP_dT = R*x0 - da_alpha_dT*x1
    dP_dV = x5*x7 - x3*x4
    d2P_dT2 = -d2a_alpha_dT2*x1

    d2P_dV2 = (x7 + x3*x4*x0 - a_alpha*x5*x17*x1)
    d2P_dV2 += d2P_dV2

    d2P_dTdV = da_alpha_dT*x17 - R*x4
    H_dep = x12*(T*da_alpha_dT - a_alpha) - x3 + x8

    t1 = (x3*x0/P)
    S_dep = -R*log(t1) + da_alpha_dT*x12  # Consider Real part of the log only via log(x**2)/2 = Re(log(x))
#        S_dep = -R_2*log(t1*t1) + da_alpha_dT*x12  # Consider Real part of the log only via log(x**2)/2 = Re(log(x))
    x18 = x16 - x15
    x19 = (x14 + x18)/(x14 - x18)
    Cv_dep = T*d2a_alpha_dT2*x11*(log(x19)) # Consider Real part of the log only via log(x**2)/2 = Re(log(x))
    return dP_dT, dP_dV, d2P_dT2, d2P_dV2, d2P_dTdV, H_dep, S_dep, Cv_dep


def main_derivatives_and_departures_VDW(T, P, V, b, delta, epsilon, a_alpha,
                                    da_alpha_dT, d2a_alpha_dT2):
    '''Re-implementation of derivatives and excess property calculations,
    as ZeroDivisionError errors occur with the general solution. The
    following derivation is the source of these formulas.

    >>> from sympy import *
    >>> P, T, V, R, b, a = symbols('P, T, V, R, b, a')
    >>> P_vdw = R*T/(V-b) - a/(V*V)
    >>> vdw = P_vdw - P
    >>>
    >>> dP_dT = diff(vdw, T)
    >>> dP_dV = diff(vdw, V)
    >>> d2P_dT2 = diff(vdw, T, 2)
    >>> d2P_dV2 = diff(vdw, V, 2)
    >>> d2P_dTdV = diff(vdw, T, V)
    >>> H_dep = integrate(T*dP_dT - P_vdw, (V, oo, V))
    >>> H_dep += P*V - R*T
    >>> S_dep = integrate(dP_dT - R/V, (V,oo,V))
    >>> S_dep += R*log(P*V/(R*T))
    >>> Cv_dep = T*integrate(d2P_dT2, (V,oo,V))
    >>>
    >>> dP_dT, dP_dV, d2P_dT2, d2P_dV2, d2P_dTdV, H_dep, S_dep, Cv_dep
    (R/(V - b), -R*T/(V - b)**2 + 2*a/V**3, 0, 2*(R*T/(V - b)**3 - 3*a/V**4), -R/(V - b)**2, P*V - R*T - a/V, R*(-log(V) + log(V - b)) + R*log(P*V/(R*T)), 0)
    '''
    V_inv = 1.0/V
    V_inv2 = V_inv*V_inv
    Vmb = V - b
    Vmb_inv = 1.0/Vmb
    dP_dT = R*Vmb_inv
    dP_dV = -R*T*Vmb_inv*Vmb_inv + 2.0*a_alpha*V_inv*V_inv2
    d2P_dT2 = 0.0
    d2P_dV2 = 2.0*(R*T*Vmb_inv*Vmb_inv*Vmb_inv - 3.0*a_alpha*V_inv2*V_inv2) # Causes issues at low T when V fourth power fails
    d2P_dTdV = -R*Vmb_inv*Vmb_inv
    H_dep = P*V - R*T - a_alpha*V_inv
    S_dep = R*(-log(V) + log(Vmb)) + R*log(P*V/(R*T))
    Cv_dep = 0.0
    return (dP_dT, dP_dV, d2P_dT2, d2P_dV2, d2P_dTdV, H_dep, S_dep, Cv_dep)


def eos_lnphi(T, P, V, b, delta, epsilon, a_alpha):
    r'''Calculate the log fugacity coefficient of the general cubic equation
    of state form.

    .. math::
        \ln \phi = \frac{P V}{R T} + \log{\left(V \right)} - \log{\left(\frac{P
        V}{R T} \right)} - \log{\left(V - b \right)} - 1 - \frac{2 a {\alpha}
        \operatorname{atanh}{\left(\frac{2 V}{\sqrt{\delta^{2} - 4 \epsilon}}
        + \frac{\delta}{\sqrt{\delta^{2} - 4 \epsilon}} \right)}}
        {R T \sqrt{\delta^{2} - 4 \epsilon}}

    Parameters
    ----------
    T : float
        Temperature, [K]
    P : float
        Pressure, [Pa]
    V : float
        Molar volume, [m^3/mol]
    b : float
        Coefficient calculated by EOS-specific method, [m^3/mol]
    delta : float
        Coefficient calculated by EOS-specific method, [m^3/mol]
    epsilon : float
        Coefficient calculated by EOS-specific method, [m^6/mol^2]
    a_alpha : float
        Coefficient calculated by EOS-specific method, [J^2/mol^2/Pa]

    Returns
    -------
    lnphi : float
        Log fugacity coefficient, [-]

    Examples
    --------
    >>> eos_lnphi(299.0, 100000.0, 0.00013128, 0.000109389, 0.00021537, -1.1964711e-08, 3.8056296)
    -1.560560970726

    '''
    RT = R*T
    RT_inv = 1.0/RT
    x0 = 1.0/sqrt(delta*delta - 4.0*epsilon)

    arg = 2.0*V*x0 + delta*x0
    fancy = catanh(arg).real

# Possible optimization, numerical analysis required.
#     arg2 = (arg + 1.0)/(arg - 1.0)
#     fancy = 0.25*log(arg2*arg2)

    return (P*V*RT_inv + log(RT/(P*(V-b))) - 1.0
            - 2.0*a_alpha*fancy*RT_inv*x0)

class GCEOS(object):
    r'''Class for solving a generic Pressure-explicit three-parameter cubic
    equation of state. Does not implement any parameters itself; must be
    subclassed by an equation of state class which uses it. Works for mixtures
    or pure species for all properties except fugacity. All properties are
    derived with the CAS SymPy, not relying on any derivations previously
    published.

    .. math::
        P=\frac{RT}{V-b}-\frac{a\alpha(T)}{V^2 + \delta V + \epsilon}

    The main methods (in order they are called) are :obj:`GCEOS.solve`, :obj:`GCEOS.set_from_PT`,
    :obj:`GCEOS.volume_solutions`, and :obj:`GCEOS.set_properties_from_solution`.

    :obj:`GCEOS.solve` calls :obj:`GCEOS.check_sufficient_inputs`, which checks if two of `T`, `P`,
    and `V` were set. It then solves for the
    remaining variable. If `T` is missing, method :obj:`GCEOS.solve_T` is used; it is
    parameter specific, and so must be implemented in each specific EOS.
    If `P` is missing, it is directly calculated. If `V` is missing, it
    is calculated with the method :obj:`GCEOS.volume_solutions`. At this point, either
    three possible volumes or one user specified volume are known. The
    value of `a_alpha`, and its first and second temperature derivative are
    calculated with the EOS-specific method :obj:`GCEOS.a_alpha_and_derivatives`.

    If `V` is not provided, :obj:`GCEOS.volume_solutions` calculates the three
    possible molar volumes which are solutions to the EOS; in the single-phase
    region, only one solution is real and correct. In the two-phase region, all
    volumes are real, but only the largest and smallest solution are physically
    meaningful, with the largest being that of the gas and the smallest that of
    the liquid.

    :obj:`GCEOS.set_from_PT` is called to sort out the possible molar volumes. For the
    case of a user-specified `V`, the possibility of there existing another
    solution is ignored for speed. If there is only one real volume, the
    method :obj:`GCEOS.set_properties_from_solution` is called with it. If there are
    two real volumes, :obj:`GCEOS.set_properties_from_solution` is called once with each
    volume. The phase is returned by :obj:`GCEOS.set_properties_from_solution`, and the
    volumes is set to either :obj:`GCEOS.V_l` or :obj:`GCEOS.V_g` as appropriate.

    :obj:`GCEOS.set_properties_from_solution` is a large function which calculates all relevant
    partial derivatives and properties of the EOS. 17 derivatives and excess
    enthalpy and entropy are calculated first.
    Finally, it sets all these properties as attibutes for either
    the liquid or gas phase with the convention of adding on `_l` or `_g` to
    the variable names, respectively.


    Attributes
    ----------
    T : float
        Temperature of cubic EOS state, [K]
    P : float
        Pressure of cubic EOS state, [Pa]
    a : float
        `a` parameter of cubic EOS; formulas vary with the EOS, [Pa*m^6/mol^2]
    b : float
        `b` parameter of cubic EOS; formulas vary with the EOS, [m^3/mol]
    delta : float
        Coefficient calculated by EOS-specific method, [m^3/mol]
    epsilon : float
        Coefficient calculated by EOS-specific method, [m^6/mol^2]
    a_alpha : float
        Coefficient calculated by EOS-specific method, [J^2/mol^2/Pa]
    da_alpha_dT : float
        Temperature derivative of :math:`a \alpha` calculated by EOS-specific
        method, [J^2/mol^2/Pa/K]
    d2a_alpha_dT2 : float
        Second temperature derivative of :math:`a \alpha` calculated by
        EOS-specific method, [J^2/mol^2/Pa/K**2]
    Zc : float
        Critical compressibility of cubic EOS state, [-]
    phase : str
        One of 'l', 'g', or 'l/g' to represent whether or not there is a
        liquid-like solution, vapor-like solution, or both available, [-]
    raw_volumes : list[(float, complex), 3]
        Calculated molar volumes from the volume solver; depending on the state
        and selected volume solver, imaginary volumes may be represented by 0
        or -1j to save the time of actually calculating them, [m^3/mol]
    V_l : float
        Liquid phase molar volume, [m^3/mol]
    V_g : float
        Vapor phase molar volume, [m^3/mol]
    V : float or None
        Molar volume specified as input; otherwise None, [m^3/mol]
    Z_l : float
        Liquid phase compressibility, [-]
    Z_g : float
        Vapor phase compressibility, [-]
    PIP_l : float
        Liquid phase phase identification parameter, [-]
    PIP_g : float
        Vapor phase phase identification parameter, [-]
    dP_dT_l : float
        Liquid phase temperature derivative of pressure at constant volume,
        [Pa/K].

        .. math::
            \left(\frac{\partial P}{\partial T}\right)_V = \frac{R}{V - b}
            - \frac{a \frac{d \alpha{\left (T \right )}}{d T}}{V^{2} + V \delta
            + \epsilon}
    dP_dT_g : float
        Vapor phase temperature derivative of pressure at constant volume,
        [Pa/K].

        .. math::
            \left(\frac{\partial P}{\partial T}\right)_V = \frac{R}{V - b}
            - \frac{a \frac{d \alpha{\left (T \right )}}{d T}}{V^{2} + V \delta
            + \epsilon}
    dP_dV_l : float
        Liquid phase volume derivative of pressure at constant temperature,
        [Pa*mol/m^3].

        .. math::
            \left(\frac{\partial P}{\partial V}\right)_T = - \frac{R T}{\left(
            V - b\right)^{2}} - \frac{a \left(- 2 V - \delta\right) \alpha{
            \left (T \right )}}{\left(V^{2} + V \delta + \epsilon\right)^{2}}
    dP_dV_g : float
        Gas phase volume derivative of pressure at constant temperature,
        [Pa*mol/m^3].

        .. math::
            \left(\frac{\partial P}{\partial V}\right)_T = - \frac{R T}{\left(
            V - b\right)^{2}} - \frac{a \left(- 2 V - \delta\right) \alpha{
            \left (T \right )}}{\left(V^{2} + V \delta + \epsilon\right)^{2}}
    dV_dT_l : float
        Liquid phase temperature derivative of volume at constant pressure,
        [m^3/(mol*K)].

        .. math::
            \left(\frac{\partial V}{\partial T}\right)_P =-\frac{
            \left(\frac{\partial P}{\partial T}\right)_V}{
            \left(\frac{\partial P}{\partial V}\right)_T}
    dV_dT_g : float
        Gas phase temperature derivative of volume at constant pressure,
        [m^3/(mol*K)].

        .. math::
            \left(\frac{\partial V}{\partial T}\right)_P =-\frac{
            \left(\frac{\partial P}{\partial T}\right)_V}{
            \left(\frac{\partial P}{\partial V}\right)_T}
    dV_dP_l : float
        Liquid phase pressure derivative of volume at constant temperature,
        [m^3/(mol*Pa)].

        .. math::
            \left(\frac{\partial V}{\partial P}\right)_T =-\frac{
            \left(\frac{\partial V}{\partial T}\right)_P}{
            \left(\frac{\partial P}{\partial T}\right)_V}
    dV_dP_g : float
        Gas phase pressure derivative of volume at constant temperature,
        [m^3/(mol*Pa)].

        .. math::
            \left(\frac{\partial V}{\partial P}\right)_T =-\frac{
            \left(\frac{\partial V}{\partial T}\right)_P}{
            \left(\frac{\partial P}{\partial T}\right)_V}
    dT_dV_l : float
        Liquid phase volume derivative of temperature at constant pressure,
        [K*mol/m^3].

        .. math::
            \left(\frac{\partial T}{\partial V}\right)_P = \frac{1}
            {\left(\frac{\partial V}{\partial T}\right)_P}
    dT_dV_g : float
        Gas phase volume derivative of temperature at constant pressure,
        [K*mol/m^3]. See :obj:`GCEOS.set_properties_from_solution` for
        the formula.
    dT_dP_l : float
        Liquid phase pressure derivative of temperature at constant volume,
        [K/Pa].

        .. math::
            \left(\frac{\partial T}{\partial P}\right)_V = \frac{1}
            {\left(\frac{\partial P}{\partial T}\right)_V}
    dT_dP_g : float
        Gas phase pressure derivative of temperature at constant volume,
        [K/Pa].

        .. math::
            \left(\frac{\partial T}{\partial P}\right)_V = \frac{1}
            {\left(\frac{\partial P}{\partial T}\right)_V}
    d2P_dT2_l : float
        Liquid phase second derivative of pressure with respect to temperature
        at constant volume, [Pa/K^2].

        .. math::
            \left(\frac{\partial^2  P}{\partial T^2}\right)_V =  - \frac{a
            \frac{d^{2} \alpha{\left (T \right )}}{d T^{2}}}{V^{2} + V \delta
            + \epsilon}
    d2P_dT2_g : float
        Gas phase second derivative of pressure with respect to temperature
        at constant volume, [Pa/K^2].

        .. math::
            \left(\frac{\partial^2  P}{\partial T^2}\right)_V =  - \frac{a
            \frac{d^{2} \alpha{\left (T \right )}}{d T^{2}}}{V^{2} + V \delta
            + \epsilon}
    d2P_dV2_l : float
        Liquid phase second derivative of pressure with respect to volume
        at constant temperature, [Pa*mol^2/m^6].

        .. math::
            \left(\frac{\partial^2  P}{\partial V^2}\right)_T = 2 \left(\frac{
            R T}{\left(V - b\right)^{3}} - \frac{a \left(2 V + \delta\right)^{
            2} \alpha{\left (T \right )}}{\left(V^{2} + V \delta + \epsilon
            \right)^{3}} + \frac{a \alpha{\left (T \right )}}{\left(V^{2} + V
            \delta + \epsilon\right)^{2}}\right)
    d2P_dTdV_l : float
        Liquid phase second derivative of pressure with respect to volume
        and then temperature, [Pa*mol/(K*m^3)].

        .. math::
            \left(\frac{\partial^2 P}{\partial T \partial V}\right) = - \frac{
            R}{\left(V - b\right)^{2}} + \frac{a \left(2 V + \delta\right)
            \frac{d \alpha{\left (T \right )}}{d T}}{\left(V^{2} + V \delta
            + \epsilon\right)^{2}}
    d2P_dTdV_g : float
        Gas phase second derivative of pressure with respect to volume
        and then temperature, [Pa*mol/(K*m^3)].

        .. math::
            \left(\frac{\partial^2 P}{\partial T \partial V}\right) = - \frac{
            R}{\left(V - b\right)^{2}} + \frac{a \left(2 V + \delta\right)
            \frac{d \alpha{\left (T \right )}}{d T}}{\left(V^{2} + V \delta
            + \epsilon\right)^{2}}
    H_dep_l : float
        Liquid phase departure enthalpy, [J/mol]. See
        :obj:`GCEOS.set_properties_from_solution` for the formula.
    H_dep_g : float
        Gas phase departure enthalpy, [J/mol]. See
        :obj:`GCEOS.set_properties_from_solution` for the formula.
    S_dep_l : float
        Liquid phase departure entropy, [J/(mol*K)]. See
        :obj:`GCEOS.set_properties_from_solution` for the formula.
    S_dep_g : float
        Gas phase departure entropy, [J/(mol*K)]. See
        :obj:`GCEOS.set_properties_from_solution` for the formula.
    G_dep_l : float
        Liquid phase departure Gibbs energy, [J/mol].

        .. math::
            G_{dep} = H_{dep} - T S_{dep}
    G_dep_g : float
        Gas phase departure Gibbs energy, [J/mol].

        .. math::
            G_{dep} = H_{dep} - T S_{dep}
    Cp_dep_l : float
        Liquid phase departure heat capacity, [J/(mol*K)]

        .. math::
            C_{p, dep} = (C_p-C_v)_{\text{from EOS}} + C_{v, dep} - R
    Cp_dep_g : float
        Gas phase departure heat capacity, [J/(mol*K)]

        .. math::
            C_{p, dep} = (C_p-C_v)_{\text{from EOS}} + C_{v, dep} - R
    Cv_dep_l : float
        Liquid phase departure constant volume heat capacity, [J/(mol*K)].
        See :obj:`GCEOS.set_properties_from_solution` for
        the formula.

    Cv_dep_g : float
        Gas phase departure constant volume heat capacity, [J/(mol*K)].
        See :obj:`GCEOS.set_properties_from_solution` for
        the formula.
    c1 : float
        Full value of the constant in the `a` parameter, set in some EOSs, [-]
    c2 : float
        Full value of the constant in the `b` parameter, set in some EOSs, [-]

    A_dep_g
    A_dep_l
    beta_g
    beta_l
    Cp_minus_Cv_g
    Cp_minus_Cv_l
    d2a_alpha_dTdP_g_V
    d2a_alpha_dTdP_l_V
    d2H_dep_dT2_g
    d2H_dep_dT2_g_P
    d2H_dep_dT2_g_V
    d2H_dep_dT2_l
    d2H_dep_dT2_l_P
    d2H_dep_dT2_l_V
    d2H_dep_dTdP_g
    d2H_dep_dTdP_l
    d2P_drho2_g
    d2P_drho2_l
    d2P_dT2_PV_g
    d2P_dT2_PV_l
    d2P_dTdP_g
    d2P_dTdP_l
    d2P_dTdrho_g
    d2P_dTdrho_l
    d2P_dVdP_g
    d2P_dVdP_l
    d2P_dVdT_g
    d2P_dVdT_l
    d2P_dVdT_TP_g
    d2P_dVdT_TP_l
    d2rho_dP2_g
    d2rho_dP2_l
    d2rho_dPdT_g
    d2rho_dPdT_l
    d2rho_dT2_g
    d2rho_dT2_l
    d2S_dep_dT2_g
    d2S_dep_dT2_g_V
    d2S_dep_dT2_l
    d2S_dep_dT2_l_V
    d2S_dep_dTdP_g
    d2S_dep_dTdP_l
    d2T_dP2_g
    d2T_dP2_l
    d2T_dPdrho_g
    d2T_dPdrho_l
    d2T_dPdV_g
    d2T_dPdV_l
    d2T_drho2_g
    d2T_drho2_l
    d2T_dV2_g
    d2T_dV2_l
    d2T_dVdP_g
    d2T_dVdP_l
    d2V_dP2_g
    d2V_dP2_l
    d2V_dPdT_g
    d2V_dPdT_l
    d2V_dT2_g
    d2V_dT2_l
    d2V_dTdP_g
    d2V_dTdP_l
    d3a_alpha_dT3
    da_alpha_dP_g_V
    da_alpha_dP_l_V
    dbeta_dP_g
    dbeta_dP_l
    dbeta_dT_g
    dbeta_dT_l
    dfugacity_dP_g
    dfugacity_dP_l
    dfugacity_dT_g
    dfugacity_dT_l
    dH_dep_dP_g
    dH_dep_dP_g_V
    dH_dep_dP_l
    dH_dep_dP_l_V
    dH_dep_dT_g
    dH_dep_dT_g_V
    dH_dep_dT_l
    dH_dep_dT_l_V
    dH_dep_dV_g_P
    dH_dep_dV_g_T
    dH_dep_dV_l_P
    dH_dep_dV_l_T
    dP_drho_g
    dP_drho_l
    dphi_dP_g
    dphi_dP_l
    dphi_dT_g
    dphi_dT_l
    drho_dP_g
    drho_dP_l
    drho_dT_g
    drho_dT_l
    dS_dep_dP_g
    dS_dep_dP_g_V
    dS_dep_dP_l
    dS_dep_dP_l_V
    dS_dep_dT_g
    dS_dep_dT_g_V
    dS_dep_dT_l
    dS_dep_dT_l_V
    dS_dep_dV_g_P
    dS_dep_dV_g_T
    dS_dep_dV_l_P
    dS_dep_dV_l_T
    dT_drho_g
    dT_drho_l
    dZ_dP_g
    dZ_dP_l
    dZ_dT_g
    dZ_dT_l
    fugacity_g
    fugacity_l
    kappa_g
    kappa_l
    lnphi_g
    lnphi_l
    more_stable_phase
    mpmath_volume_ratios
    mpmath_volumes
    mpmath_volumes_float
    phi_g
    phi_l
    rho_g
    rho_l
    sorted_volumes
    state_specs
    U_dep_g
    U_dep_l
    Vc
    V_dep_g
    V_dep_l
    V_g_mpmath
    V_l_mpmath
    '''
    # Slots does not help performance in either implementation
    kwargs = {}
    '''Dictionary which holds input parameters to an EOS which are non-standard;
    this excludes `T`, `P`, `V`, `omega`, `Tc`, `Pc`, `Vc` but includes EOS
    specific parameters like `S1` and `alpha_coeffs`.
    '''

    N = 1
    '''The number of components in the EOS'''
    scalar = True

    multicomponent = False
    '''Whether or not the EOS is multicomponent or not'''
    _P_zero_l_cheb_coeffs = None
    P_zero_l_cheb_limits = (0.0, 0.0)
    _P_zero_g_cheb_coeffs = None
    P_zero_g_cheb_limits = (0.0, 0.0)
    Psat_cheb_range = (0.0, 0.0)

    main_derivatives_and_departures = staticmethod(main_derivatives_and_departures)

    c1 = None
    '''Parameter used by some equations of state in the `a` calculation'''
    c2 = None
    '''Parameter used by some equations of state in the `b` calculation'''

    nonstate_constants = ('Tc', 'Pc', 'omega', 'kwargs', 'a', 'b', 'delta', 'epsilon')
    kwargs_keys = tuple()
    
    if not is_micropython:
        def __init_subclass__(cls):
            cls.__full_path__ = "%s.%s" %(cls.__module__, cls.__qualname__)
    else:
        __full_path__ = None

    def state_hash(self):
        r'''Basic method to calculate a hash of the state of the model and its
        model parameters.

        Note that the hashes should only be compared on the same system running
        in the same process!

        Returns
        -------
        state_hash : int
            Hash of the object's model parameters and state, [-]
        '''
        if self.multicomponent:
            comp = self.zs
        else:
            comp = 0
        return hash_any_primitive((self.model_hash(), self.T, self.P, self.V, comp))

    def model_hash(self):
        r'''Basic method to calculate a hash of the non-state parts of the model
        This is useful for comparing to models to
        determine if they are the same, i.e. in a VLL flash it is important to
        know if both liquids have the same model.

        Note that the hashes should only be compared on the same system running
        in the same process!

        Returns
        -------
        model_hash : int
            Hash of the object's model parameters, [-]
        '''
        try:
            return self._model_hash
        except AttributeError:
            pass
        h = hash(self.__class__.__name__)
        for s in self.nonstate_constants:
            try:
                h = hash((h, s, hash_any_primitive(getattr(self, s))))
            except AttributeError:
                pass
        self._model_hash = h
        return h

    def __hash__(self):
        r'''Method to calculate and return a hash representing the exact state
        of the object.

        Returns
        -------
        hash : int
            Hash of the object, [-]
        '''
        d = self.__dict__
        ans = hash_any_primitive((self.__class__.__name__, d))
        return ans

    def __eq__(self, other):
        return self.__hash__() == hash(other)


    @property
    def state_specs(self):
        '''Convenience method to return the two specified state specs (`T`,
        `P`, or `V`) as a dictionary.

        Examples
        --------
        >>> PR(Tc=507.6, Pc=3025000.0, omega=0.2975, T=500.0, V=1.0).state_specs
        {'T': 500.0, 'V': 1.0}
        '''
        d = {}
        if hasattr(self, 'no_T_spec') and self.no_T_spec:
            d['P'] = self.P
            d['V'] = self.V
        elif self.V is not None:
            d['T'] = self.T
            d['V'] = self.V
        else:
            d['T'] = self.T
            d['P'] = self.P
        return d

    def __repr__(self):
        '''Create a string representation of the EOS - by default, include
        all parameters so as to make it easy to construct new instances from
        states. Includes the two specified state variables, `Tc`, `Pc`, `omega`
        and any `kwargs`.

        Returns
        -------
        recreation : str
            String which is valid Python and recreates the current state of
            the object if ran, [-]

        Examples
        --------
        >>> eos = PR(Tc=507.6, Pc=3025000.0, omega=0.2975, T=400.0, P=1e6)
        >>> eos
        PR(Tc=507.6, Pc=3025000.0, omega=0.2975, T=400.0, P=1000000.0)
        '''
        s = '%s(Tc=%s, Pc=%s, omega=%s, ' %(self.__class__.__name__, repr(self.Tc), repr(self.Pc), repr(self.omega))
        for k, v in self.kwargs.items():
            s += '%s=%s, ' %(k, v)

        if hasattr(self, 'no_T_spec') and self.no_T_spec:
            s += 'P=%s, V=%s' %(repr(self.P), repr(self.V))
        elif self.V is not None:
            s += 'T=%s, V=%s' %(repr(self.T), repr(self.V))
        else:
            s += 'T=%s, P=%s' %(repr(self.T), repr(self.P))
        s += ')'
        return s

    def as_json(self):
        r'''Method to create a JSON-friendly serialization of the eos
        which can be stored, and reloaded later.

        Returns
        -------
        json_repr : dict
            JSON-friendly representation, [-]

        Notes
        -----

        Examples
        --------
        >>> import json
        >>> eos = MSRKTranslated(Tc=507.6, Pc=3025000, omega=0.2975, c=22.0561E-6, M=0.7446, N=0.2476, T=250., P=1E6)
        >>> assert eos == MSRKTranslated.from_json(json.loads(json.dumps(eos.as_json())))
        '''
        # vaguely jsonpickle compatible
        d = self.__dict__.copy()
        if not self.scalar:
            d = serialize.arrays_to_lists(d)
        # TODO: delete kwargs and reconstruct it
        # Need to add all kwargs attributes
        try:
            del d['kwargs']
        except:
            pass
        d["py/object"] = self.__full_path__
        d['json_version'] = 1
        return d

    @classmethod
    def from_json(cls, json_repr):
        r'''Method to create a eos from a JSON
        serialization of another eos.

        Parameters
        ----------
        json_repr : dict
            JSON-friendly representation, [-]

        Returns
        -------
        eos : :obj:`GCEOS`
            Newly created object from the json serialization, [-]

        Notes
        -----
        It is important that the input string be in the same format as that
        created by :obj:`GCEOS.as_json`.

        Examples
        --------
        >>> eos = MSRKTranslated(Tc=507.6, Pc=3025000, omega=0.2975, c=22.0561E-6, M=0.7446, N=0.2476, T=250., P=1E6)
        >>> string = eos.as_json()
        >>> new_eos = GCEOS.from_json(string)
        >>> assert eos.__dict__ == new_eos.__dict__
        '''
        d = json_repr
        eos_name = d['py/object']
        del d['py/object']
        del d['json_version']

        try:
            d['raw_volumes'] = tuple(d['raw_volumes'])
        except:
            pass

        try:
            d['alpha_coeffs'] = tuple(d['alpha_coeffs'])
        except:
            pass

        eos = eos_full_path_dict[eos_name]

        if eos.kwargs_keys:
            d['kwargs'] = {k: d[k] for k in eos.kwargs_keys}
            try:
                d['kwargs']['alpha_coeffs'] = tuple(d['kwargs']['alpha_coeffs'])
            except:
                pass

        new = eos.__new__(eos)
        new.__dict__ = d
        return new

    def check_sufficient_inputs(self):
        '''Method to an exception if none of the pairs (T, P), (T, V), or
        (P, V) are given. '''
        if not ((self.T is not None and self.P is not None) or
                (self.T is not None and self.V is not None) or
                (self.P is not None and self.V is not None)):
            raise ValueError('Either T and P, or T and V, or P and V are required')


    def solve(self, pure_a_alphas=True, only_l=False, only_g=False, full_alphas=True):
        '''First EOS-generic method; should be called by all specific EOSs.
        For solving for `T`, the EOS must provide the method `solve_T`.
        For all cases, the EOS must provide `a_alpha_and_derivatives`.
        Calls `set_from_PT` once done.
        '''
#        self.check_sufficient_inputs()

        if self.V is not None:
            V = self.V
            if self.P is not None:
                solution = 'g' if (only_g and not only_l) else ('l' if only_l else None)
                self.T = self.solve_T(self.P, V, solution=solution)
                self.a_alpha, self.da_alpha_dT, self.d2a_alpha_dT2 = self.a_alpha_and_derivatives(self.T, pure_a_alphas=pure_a_alphas)
            elif self.T is not None:
                self.a_alpha, self.da_alpha_dT, self.d2a_alpha_dT2 = self.a_alpha_and_derivatives(self.T, pure_a_alphas=pure_a_alphas)

                # Tested to change the result at the 7th decimal once
#                V_r3 = V**(1.0/3.0)
#                T, b, a_alpha, delta, epsilon = self.T, self.b, self.a_alpha, self.delta, self.epsilon
#                P = R*T/(V-b) - a_alpha/((V_r3*V_r3)*(V_r3*(V+delta)) + epsilon)
#
#                for _ in range(10):
#                    err = -T + (P*V**3 - P*V**2*b + P*V**2*delta - P*V*b*delta + P*V*epsilon - P*b*epsilon + V*a_alpha - a_alpha*b)/(R*(V**2 + V*delta + epsilon))
#                    derr = (V**3 - V**2*b + V**2*delta - V*b*delta + V*epsilon - b*epsilon)/(R*(V**2 + V*delta + epsilon))
#                    P = P - err/derr
#                self.P = P
                # Equation re-aranged to hopefully solve better

                # Allow mpf multiple precision volume for flash initialization
                # DO NOT TAKE OUT FLOAT CONVERSION!
                T = self.T
                if not isinstance(V, (float, int)):
                    import mpmath as mp
                    # mp.mp.dps = 50 # Do not need more decimal places than needed
                    # Need to complete the calculation with the RT term having higher precision as well
                    T = mp.mpf(T)
                self.P = float(R*T/(V-self.b) - self.a_alpha/(V*V + self.delta*V + self.epsilon))
                if self.P <= 0.0:
                    raise ValueError("TV inputs result in negative pressure of %f Pa" %(self.P))
#                self.P = R*self.T/(V-self.b) - self.a_alpha/(V*(V + self.delta) + self.epsilon)
            else:
                raise ValueError("Two specs are required")
            Vs = [V, 1.0j, 1.0j]
        elif self.T is None or self.P is None:
            raise ValueError("Two specs are required")
        else:
            if full_alphas:
                self.a_alpha, self.da_alpha_dT, self.d2a_alpha_dT2 = self.a_alpha_and_derivatives(self.T, pure_a_alphas=pure_a_alphas)
            else:
                self.a_alpha = self.a_alpha_and_derivatives(self.T, full=False, pure_a_alphas=pure_a_alphas)
                self.da_alpha_dT, self.d2a_alpha_dT2 = -5e-3, 1.5e-5
            self.raw_volumes = Vs = self.volume_solutions(self.T, self.P, self.b, self.delta, self.epsilon, self.a_alpha)
        self.set_from_PT(Vs, only_l=only_l, only_g=only_g)

    def resolve_full_alphas(self):
        '''Generic method to resolve the eos with fully calculated alpha
        derviatives. Re-calculates properties with the new alpha derivatives
        for any previously solved roots.
        '''
        self.a_alpha, self.da_alpha_dT, self.d2a_alpha_dT2 = self.a_alpha_and_derivatives(self.T, full=True, pure_a_alphas=False)
        self.set_from_PT(self.raw_volumes, only_l=hasattr(self, 'V_l'), only_g=hasattr(self, 'V_g'))

    def solve_missing_volumes(self):
        r'''Generic method to ensure both volumes, if solutions are physical,
        have calculated properties. This effectively un-does the optimization
        of the `only_l` and `only_g` keywords.
        '''
        if self.phase == 'l/g':
            try:
                self.V_l
            except:
                self.set_from_PT(self.raw_volumes, only_l=True, only_g=False)
            try:
                self.V_g
            except:
                self.set_from_PT(self.raw_volumes, only_l=False, only_g=True)


    def set_from_PT(self, Vs, only_l=False, only_g=False):
        r'''Counts the number of real volumes in `Vs`, and determines what to do.
        If there is only one real volume, the method
        `set_properties_from_solution` is called with it. If there are
        two real volumes, `set_properties_from_solution` is called once with
        each volume. The phase is returned by `set_properties_from_solution`,
        and the volumes is set to either `V_l` or `V_g` as appropriate.

        Parameters
        ----------
        Vs : list[float]
            Three possible molar volumes, [m^3/mol]
        only_l : bool
            When true, if there is a liquid and a vapor root, only the liquid
            root (and properties) will be set.
        only_g : bool
            When true, if there is a liquid and a vapor root, only the vapor
            root (and properties) will be set.

        Notes
        -----
        An optimization attempt was made to remove min() and max() from this
        function; that is indeed possible, but the check for handling if there
        are two or three roots makes it not worth it.
        '''
#        good_roots = [i.real for i in Vs if i.imag == 0.0 and i.real > 0.0]
#        good_root_count = len(good_roots)
            # All roots will have some imaginary component; ignore them if > 1E-9 (when using a solver that does not strip them)
        b = self.b
#        good_roots = [i.real for i in Vs if (i.real ==0 or abs(i.imag/i.real) < 1E-12) and i.real > 0.0]
        good_roots = [i.real for i in Vs if (i.real > b and (i.real == 0.0 or abs(i.imag/i.real) < 1E-12))]

        # Counter for the case of testing volume solutions that don't work
#        good_roots = [i.real for i in Vs if (i.real > 0.0 and (i.real == 0.0 or abs(i.imag) < 1E-9))]
        good_root_count = len(good_roots)

        if good_root_count == 1 or (good_roots[0] == good_roots[1]):
            self.phase = self.set_properties_from_solution(self.T, self.P,
                                                           good_roots[0], b,
                                                           self.delta, self.epsilon,
                                                           self.a_alpha, self.da_alpha_dT,
                                                           self.d2a_alpha_dT2)

            if self.N == 1 and (
                    (self.multicomponent and (self.Tcs[0] == self.T and self.Pcs[0] == self.P))
                    or (not self.multicomponent and self.Tc == self.T and self.Pc == self.P)):
                # Do not have any tests for this - not good!

                force_l = not self.phase == 'l'
                force_g = not self.phase == 'g'
                self.set_properties_from_solution(self.T, self.P,
                                                  good_roots[0], b,
                                                  self.delta, self.epsilon,
                                                  self.a_alpha, self.da_alpha_dT,
                                                  self.d2a_alpha_dT2,
                                                  force_l=force_l,
                                                  force_g=force_g)
                self.phase = 'l/g'
        elif good_root_count > 1:
            V_l, V_g = min(good_roots), max(good_roots)

            if not only_g:
                self.set_properties_from_solution(self.T, self.P, V_l, b,
                                                   self.delta, self.epsilon,
                                                   self.a_alpha, self.da_alpha_dT,
                                                   self.d2a_alpha_dT2,
                                                   force_l=True)
            if not only_l:
                self.set_properties_from_solution(self.T, self.P, V_g, b,
                                                   self.delta, self.epsilon,
                                                   self.a_alpha, self.da_alpha_dT,
                                                   self.d2a_alpha_dT2, force_g=True)
            self.phase = 'l/g'
        else:
            # Even in the case of three real roots, it is still the min/max that make sense
            print([self.T, self.P, b, self.delta, self.epsilon, self.a_alpha, 'coordinates of failure'])
            if self.multicomponent:
                extra = ', zs is %s' %(self.zs)
            else:
                extra = ''
            raise ValueError('No acceptable roots were found; the roots are %s, T is %s K, P is %s Pa, a_alpha is %s, b is %s%s' %(str(Vs), str(self.T), str(self.P), str([self.a_alpha]), str([self.b]), extra))


    def set_properties_from_solution(self, T, P, V, b, delta, epsilon, a_alpha,
                                     da_alpha_dT, d2a_alpha_dT2, quick=True,
                                     force_l=False, force_g=False):
        r'''Sets all interesting properties which can be calculated from an
        EOS alone. Determines which phase the fluid is on its own; for details,
        see `phase_identification_parameter`.

        The list of properties set is as follows, with all properties suffixed
        with '_l' or '_g'.

        dP_dT, dP_dV, dV_dT, dV_dP, dT_dV, dT_dP, d2P_dT2, d2P_dV2, d2V_dT2,
        d2V_dP2, d2T_dV2, d2T_dP2, d2V_dPdT, d2P_dTdV, d2T_dPdV, H_dep, S_dep,
        G_dep and PIP.

        Parameters
        ----------
        T : float
            Temperature, [K]
        P : float
            Pressure, [Pa]
        V : float
            Molar volume, [m^3/mol]
        b : float
            Coefficient calculated by EOS-specific method, [m^3/mol]
        delta : float
            Coefficient calculated by EOS-specific method, [m^3/mol]
        epsilon : float
            Coefficient calculated by EOS-specific method, [m^6/mol^2]
        a_alpha : float
            Coefficient calculated by EOS-specific method, [J^2/mol^2/Pa]
        da_alpha_dT : float
            Temperature derivative of coefficient calculated by EOS-specific
            method, [J^2/mol^2/Pa/K]
        d2a_alpha_dT2 : float
            Second temperature derivative of coefficient calculated by
            EOS-specific method, [J^2/mol^2/Pa/K**2]
        quick : bool, optional
            Whether to use a SymPy cse-derived expression (3x faster) or
            individual formulas

        Returns
        -------
        phase : str
            Either 'l' or 'g'

        Notes
        -----
        The individual formulas for the derivatives and excess properties are
        as follows. For definitions of `beta`, see `isobaric_expansion`;
        for `kappa`, see isothermal_compressibility; for `Cp_minus_Cv`, see
        `Cp_minus_Cv`; for `phase_identification_parameter`, see
        `phase_identification_parameter`.

        First derivatives; in part using the Triple Product Rule [2]_, [3]_:

        .. math::
            \left(\frac{\partial P}{\partial T}\right)_V = \frac{R}{V - b}
            - \frac{a \frac{d \alpha{\left (T \right )}}{d T}}{V^{2} + V \delta
            + \epsilon}

        .. math::
            \left(\frac{\partial P}{\partial V}\right)_T = - \frac{R T}{\left(
            V - b\right)^{2}} - \frac{a \left(- 2 V - \delta\right) \alpha{
            \left (T \right )}}{\left(V^{2} + V \delta + \epsilon\right)^{2}}

        .. math::
            \left(\frac{\partial V}{\partial T}\right)_P =-\frac{
            \left(\frac{\partial P}{\partial T}\right)_V}{
            \left(\frac{\partial P}{\partial V}\right)_T}

        .. math::
            \left(\frac{\partial V}{\partial P}\right)_T =-\frac{
            \left(\frac{\partial V}{\partial T}\right)_P}{
            \left(\frac{\partial P}{\partial T}\right)_V}

        .. math::
            \left(\frac{\partial T}{\partial V}\right)_P = \frac{1}
            {\left(\frac{\partial V}{\partial T}\right)_P}

        .. math::
            \left(\frac{\partial T}{\partial P}\right)_V = \frac{1}
            {\left(\frac{\partial P}{\partial T}\right)_V}

        Second derivatives with respect to one variable; those of `T` and `V`
        use identities shown in [1]_ and verified numerically:

        .. math::
            \left(\frac{\partial^2  P}{\partial T^2}\right)_V =  - \frac{a
            \frac{d^{2} \alpha{\left (T \right )}}{d T^{2}}}{V^{2} + V \delta
            + \epsilon}

        .. math::
            \left(\frac{\partial^2  P}{\partial V^2}\right)_T = 2 \left(\frac{
            R T}{\left(V - b\right)^{3}} - \frac{a \left(2 V + \delta\right)^{
            2} \alpha{\left (T \right )}}{\left(V^{2} + V \delta + \epsilon
            \right)^{3}} + \frac{a \alpha{\left (T \right )}}{\left(V^{2} + V
            \delta + \epsilon\right)^{2}}\right)

        Second derivatives with respect to the other two variables; those of
        `T` and `V` use identities shown in [1]_ and verified numerically:

        .. math::
            \left(\frac{\partial^2 P}{\partial T \partial V}\right) = - \frac{
            R}{\left(V - b\right)^{2}} + \frac{a \left(2 V + \delta\right)
            \frac{d \alpha{\left (T \right )}}{d T}}{\left(V^{2} + V \delta
            + \epsilon\right)^{2}}

        Excess properties

        .. math::
            H_{dep} = \int_{\infty}^V \left[T\frac{\partial P}{\partial T}_V
            - P\right]dV + PV - RT= P V - R T + \frac{2}{\sqrt{
            \delta^{2} - 4 \epsilon}} \left(T a \frac{d \alpha{\left (T \right
            )}}{d T}  - a \alpha{\left (T \right )}\right) \operatorname{atanh}
            {\left (\frac{2 V + \delta}{\sqrt{\delta^{2} - 4 \epsilon}}
            \right)}

        .. math::
            S_{dep} = \int_{\infty}^V\left[\frac{\partial P}{\partial T}
            - \frac{R}{V}\right] dV + R\ln\frac{PV}{RT} = - R \ln{\left (V
            \right )} + R \ln{\left (\frac{P V}{R T} \right )} + R \ln{\left
            (V - b \right )} + \frac{2 a \frac{d\alpha{\left (T \right )}}{d T}
            }{\sqrt{\delta^{2} - 4 \epsilon}} \operatorname{atanh}{\left (\frac
            {2 V + \delta}{\sqrt{\delta^{2} - 4 \epsilon}} \right )}

        .. math::
            G_{dep} = H_{dep} - T S_{dep}

        .. math::
            C_{v, dep} = T\int_\infty^V \left(\frac{\partial^2 P}{\partial
            T^2}\right) dV = - T a \left(\sqrt{\frac{1}{\delta^{2} - 4
            \epsilon}} \ln{\left (V - \frac{\delta^{2}}{2} \sqrt{\frac{1}{
            \delta^{2} - 4 \epsilon}} + \frac{\delta}{2} + 2 \epsilon \sqrt{
            \frac{1}{\delta^{2} - 4 \epsilon}} \right )} - \sqrt{\frac{1}{
            \delta^{2} - 4 \epsilon}} \ln{\left (V + \frac{\delta^{2}}{2}
            \sqrt{\frac{1}{\delta^{2} - 4 \epsilon}} + \frac{\delta}{2}
            - 2 \epsilon \sqrt{\frac{1}{\delta^{2} - 4 \epsilon}} \right )}
            \right) \frac{d^{2} \alpha{\left (T \right )} }{d T^{2}}

        .. math::
            C_{p, dep} = (C_p-C_v)_{\text{from EOS}} + C_{v, dep} - R


        References
        ----------
        .. [1] Thorade, Matthis, and Ali Saadat. "Partial Derivatives of
           Thermodynamic State Properties for Dynamic Simulation."
           Environmental Earth Sciences 70, no. 8 (April 10, 2013): 3497-3503.
           doi:10.1007/s12665-013-2394-z.
        .. [2] Poling, Bruce E. The Properties of Gases and Liquids. 5th
           edition. New York: McGraw-Hill Professional, 2000.
        .. [3] Walas, Stanley M. Phase Equilibria in Chemical Engineering.
           Butterworth-Heinemann, 1985.
        '''
        dP_dT, dP_dV, d2P_dT2, d2P_dV2, d2P_dTdV, H_dep, S_dep, Cv_dep = (
        self.main_derivatives_and_departures(T, P, V, b, delta, epsilon,
                                             a_alpha, da_alpha_dT,
                                             d2a_alpha_dT2))
        try:
            dV_dP = 1.0/dP_dV
        except:
            dV_dP = inf
        dT_dP = 1./dP_dT

        dV_dT = -dP_dT*dV_dP
        dT_dV = 1./dV_dT

        Z = P*V*R_inv/T
        Cp_dep = T*dP_dT*dV_dT + Cv_dep - R
        G_dep = H_dep - T*S_dep
        PIP = V*(d2P_dTdV*dT_dP - d2P_dV2*dV_dP) # phase_identification_parameter(V, dP_dT, dP_dV, d2P_dV2, d2P_dTdV)
         # 1 + 1e-14 - allow a few dozen unums of toleranve to keep ideal gas model a gas
        if force_l or (not force_g and PIP > 1.00000000000001):
            (self.V_l, self.Z_l, self.PIP_l, self.dP_dT_l, self.dP_dV_l,
             self.dV_dT_l, self.dV_dP_l, self.dT_dV_l, self.dT_dP_l,
             self.d2P_dT2_l, self.d2P_dV2_l, self.d2P_dTdV_l, self.H_dep_l,
             self.S_dep_l, self.G_dep_l, self.Cp_dep_l, self.Cv_dep_l) = (
                     V, Z, PIP, dP_dT, dP_dV, dV_dT, dV_dP, dT_dV, dT_dP,
                     d2P_dT2, d2P_dV2, d2P_dTdV, H_dep, S_dep, G_dep, Cp_dep,
                     Cv_dep)
            return 'l'
        else:
            (self.V_g, self.Z_g, self.PIP_g, self.dP_dT_g, self.dP_dV_g,
             self.dV_dT_g, self.dV_dP_g, self.dT_dV_g, self.dT_dP_g,
             self.d2P_dT2_g, self.d2P_dV2_g, self.d2P_dTdV_g, self.H_dep_g,
             self.S_dep_g, self.G_dep_g, self.Cp_dep_g, self.Cv_dep_g) = (
                     V, Z, PIP, dP_dT, dP_dV, dV_dT, dV_dP, dT_dV, dT_dP,
                     d2P_dT2, d2P_dV2, d2P_dTdV, H_dep, S_dep, G_dep, Cp_dep,
                     Cv_dep)
            return 'g'



    def a_alpha_and_derivatives(self, T, full=True, quick=True,
                                pure_a_alphas=True):
        r'''Method to calculate :math:`a \alpha` and its first and second
        derivatives.

        Parameters
        ----------
        T : float
            Temperature, [K]
        full : bool, optional
            If False, calculates and returns only `a_alpha`, [-]
        quick : bool, optional
           Legary parameter being phased out [-]
        pure_a_alphas : bool, optional
            Whether or not to recalculate the a_alpha terms of pure components
            (for the case of mixtures only) which stay the same as the
            composition changes (i.e in a PT flash); does nothing in the case
            of pure EOSs [-]

        Returns
        -------
        a_alpha : float
            Coefficient calculated by EOS-specific method, [J^2/mol^2/Pa]
        da_alpha_dT : float
            Temperature derivative of coefficient calculated by EOS-specific
            method, [J^2/mol^2/Pa/K]
        d2a_alpha_dT2 : float
            Second temperature derivative of coefficient calculated by
            EOS-specific method, [J^2/mol^2/Pa/K^2]
        '''
        if full:
            return self.a_alpha_and_derivatives_pure(T=T)
        return self.a_alpha_pure(T)

    def a_alpha_and_derivatives_pure(self, T):
        r'''Dummy method to calculate :math:`a \alpha` and its first and second
        derivatives. Should be implemented with the same function signature in
        each EOS variant; this only raises a NotImplemented Exception.
        Should return 'a_alpha', 'da_alpha_dT', and 'd2a_alpha_dT2'.

        Parameters
        ----------
        T : float
            Temperature, [K]

        Returns
        -------
        a_alpha : float
            Coefficient calculated by EOS-specific method, [J^2/mol^2/Pa]
        da_alpha_dT : float
            Temperature derivative of coefficient calculated by EOS-specific
            method, [J^2/mol^2/Pa/K]
        d2a_alpha_dT2 : float
            Second temperature derivative of coefficient calculated by
            EOS-specific method, [J^2/mol^2/Pa/K^2]
        '''
        raise NotImplementedError('a_alpha and its first and second derivatives '
                                  'should be calculated by this method, in a user subclass.')

    @property
    def d3a_alpha_dT3(self):
        r'''Method to calculate the third temperature derivative of
        :math:`a \alpha`, [J^2/mol^2/Pa/K^3]. This parameter is needed for
        some higher derivatives that are needed in some flash calculations.

        Returns
        -------
        d3a_alpha_dT3 : float
            Third temperature derivative of coefficient calculated by
            EOS-specific method, [J^2/mol^2/Pa/K^3]
        '''
        try:
            return self._d3a_alpha_dT3
        except AttributeError:
            pass
        self._d3a_alpha_dT3 = self.d3a_alpha_dT3_pure(self.T)
        return self._d3a_alpha_dT3


    def a_alpha_plot(self, Tmin=1e-4, Tmax=None, pts=1000, plot=True,
                     show=True):
        r'''Method to create a plot of the :math:`a \alpha` parameter and its
        first two derivatives. This easily allows identification of EOSs which
        are displaying inconsistent behavior.

        Parameters
        ----------
        Tmin : float
            Minimum temperature of calculation, [K]
        Tmax : float
            Maximum temperature of calculation, [K]
        pts : int, optional
            The number of temperature points to include [-]
        plot : bool
            If False, the calculated values and temperatures are returned
            without plotting the data, [-]
        show : bool
            Whether or not the plot should be rendered and shown; a handle to
            it is returned if `plot` is True for other purposes such as saving
            the plot to a file, [-]

        Returns
        -------
        Ts : list[float]
            Logarithmically spaced temperatures in specified range, [K]
        a_alpha : list[float]
            Coefficient calculated by EOS-specific method, [J^2/mol^2/Pa]
        da_alpha_dT : list[float]
            Temperature derivative of coefficient calculated by EOS-specific
            method, [J^2/mol^2/Pa/K]
        d2a_alpha_dT2 : list[float]
            Second temperature derivative of coefficient calculated by
            EOS-specific method, [J^2/mol^2/Pa/K^2]
        fig : matplotlib.figure.Figure
            Plotted figure, only returned if `plot` is True, [-]
        '''
        if Tmax is None:
            if self.multicomponent:
                Tc = self.pseudo_Tc
            else:
                Tc = self.Tc
            Tmax = Tc*10

        Ts = logspace(log10(Tmin), log10(Tmax), pts)

        a_alphas = []
        da_alphas = []
        d2a_alphas = []
        for T in Ts:
            v, d1, d2 = self.a_alpha_and_derivatives(T, full=True)
            a_alphas.append(v)
            da_alphas.append(d1)
            d2a_alphas.append(d2)

        if plot:
            import matplotlib.pyplot as plt
            fig = plt.figure()
            ax1 = fig.add_subplot(111)

            ax1.set_xlabel('Temperature [K]')
            ln0 = ax1.plot(Ts, a_alphas, 'r', label=r'$a \alpha$ [J^2/mol^2/Pa]')
            ln2 = ax1.plot(Ts, d2a_alphas, 'g', label='Second derivative [J^2/mol^2/Pa/K^2]')
            ax1.set_yscale('log')
            ax1.set_ylabel(r'$a \alpha$ and $\frac{\partial (a \alpha)^2}{\partial T^2}$')
            ax2 = ax1.twinx()
            ax2.set_yscale('symlog')
            ln1 = ax2.plot(Ts, da_alphas, 'b', label='First derivative [J^2/mol^2/Pa/K]')
            ax2.set_ylabel(r'$\frac{\partial a \alpha}{\partial T}$')
            ax1.set_title(r'$a \alpha$ vs temperature; range %.4g to %.4g' %(max(a_alphas), min(a_alphas)))

            lines = ln0 + ln1 + ln2
            labels = [l.get_label() for l in lines]
            ax1.legend(lines, labels, loc=9, bbox_to_anchor=(0.5,-0.18))
            if show:
                plt.show()
            return Ts, a_alphas, da_alphas, d2a_alphas, fig
        return Ts, a_alphas, da_alphas, d2a_alphas


    def solve_T(self, P, V, solution=None):
        '''Generic method to calculate `T` from a specified `P` and `V`.
        Provides SciPy's `newton` solver, and iterates to solve the general
        equation for `P`, recalculating `a_alpha` as a function of temperature
        using `a_alpha_and_derivatives` each iteration.

        Parameters
        ----------
        P : float
            Pressure, [Pa]
        V : float
            Molar volume, [m^3/mol]
        solution : str or None, optional
            'l' or 'g' to specify a liquid of vapor solution (if one exists);
            if None, will select a solution more likely to be real (closer to
            STP, attempting to avoid temperatures like 60000 K or 0.0001 K).

        Returns
        -------
        T : float
            Temperature, [K]
        '''
        high_prec = type(V) is not float
        denominator_inv = 1.0/(V*V + self.delta*V + self.epsilon)
        V_minus_b_inv = 1.0/(V-self.b)
        self.no_T_spec = True

        # dP_dT could be added to use a derivative-based method, however it is
        # quite costly in comparison to the extra evaluations because it
        # requires the temperature derivative of da_alpha_dT
        def to_solve(T):
            a_alpha = self.a_alpha_and_derivatives(T, full=False)
            P_calc = R*T*V_minus_b_inv - a_alpha*denominator_inv
            err = P_calc - P
            return err

        def to_solve_newton(T):
            a_alpha, da_alpha_dT, _ = self.a_alpha_and_derivatives(T, full=True)
            P_calc = R*T*V_minus_b_inv - a_alpha*denominator_inv
            err = P_calc - P
            derr_dT = R*V_minus_b_inv - denominator_inv*da_alpha_dT
            return err, derr_dT

        # import matplotlib.pyplot as plt
        # xs = np.logspace(np.log10(1), np.log10(1e12), 15000)
        # ys = np.abs([to_solve(T) for T in xs])
        # plt.loglog(xs, ys)
        # plt.show()
        # max(ys), min(ys)

        T_guess_ig = P*V*R_inv
        T_guess_liq = P*V*R_inv*1000.0 # Compressibility factor of 0.001 for liquids
        err_ig = to_solve(T_guess_ig)
        err_liq = to_solve(T_guess_liq)

        base_tol = 1e-12
        if high_prec:
            base_tol = 1e-18

        T_brenth, T_secant = None, None
        if err_ig*err_liq < 0.0 and T_guess_liq < 3e4:
            try:
                T_brenth = brenth(to_solve, T_guess_ig, T_guess_liq, xtol=base_tol,
                              fa=err_ig, fb=err_liq)
                # Check the error
                err = to_solve(T_brenth)
            except:
                pass
            # if abs(err/P) < 1e-7:
            #     return T_brenth


        if abs(err_ig) < abs(err_liq) or T_guess_liq > 20000 or solution == 'g':
            T_guess = T_guess_ig
            f0 = err_ig
        else:
            T_guess = T_guess_liq
            f0 = err_liq
        # T_guess = self.Tc*0.5
        # ytol=T_guess*1e-9,
        try:
            T_secant = secant(to_solve, T_guess, low=1e-12, xtol=base_tol, same_tol=1e4, f0=f0)
        except:
            T_guess = T_guess_ig if T_guess != T_guess_ig else T_guess_liq
            try:
                T_secant = secant(to_solve, T_guess, low=1e-12, xtol=base_tol, same_tol=1e4, f0=f0)
            except:
                if T_brenth is None:
                    # Hardcoded limits, all the cleverness sometimes does not work
                    T_brenth = brenth(to_solve, 1e-3, 1e4, xtol=base_tol)
        if solution is not None:
            if T_brenth is None or (T_secant is not None and isclose(T_brenth, T_secant, rel_tol=1e-7)):
                if T_secant is not None:
                    attempt_bounds = [(1e-3, T_secant-1e-5), (T_secant+1e-3, 1e4), (T_secant+1e-3, 1e5)]
                else:
                    attempt_bounds = [(1e-3, 1e4), (1e4, 1e5)]
                if T_guess_liq > 1e5:
                    attempt_bounds.append((1e4, T_guess_liq))
                    attempt_bounds.append((T_guess_liq, T_guess_liq*10))

                for low, high in attempt_bounds:
                    try:
                        T_brenth = brenth(to_solve, low, high, xtol=base_tol)
                        break
                    except:
                        pass
            if T_secant is None:
                if T_secant is not None:
                    attempt_bounds = [(1e-3, T_brenth-1e-5), (T_brenth+1e-3, 1e4), (T_brenth+1e-3, 1e5)]
                else:
                    attempt_bounds = [(1e4, 1e5), (1e-3, 1e4)]
                if T_guess_liq > 1e5:
                    attempt_bounds.append((1e4, T_guess_liq))
                    attempt_bounds.append((T_guess_liq, T_guess_liq*10))

                for low, high in attempt_bounds:
                    try:
                        T_secant = brenth(to_solve, low, high, xtol=base_tol)
                        break
                    except:
                        pass
        try:
            del self.a_alpha_ijs
            del self.a_alpha_roots
            del self.a_alpha_ij_roots_inv
        except AttributeError:
            pass

        if T_secant is not None:
            T_secant = float(T_secant)
        if T_brenth is not None:
            T_brenth = float(T_brenth)

        if solution is not None:
            if (T_secant is not None and T_brenth is not None):
                if solution == 'g':
                    return max(T_brenth, T_secant)
                else:
                    return min(T_brenth, T_secant)

        if T_brenth is None:
            return T_secant
        elif T_brenth is not None and T_secant is not None and (abs(T_brenth - 298.15) < abs(T_secant - 298.15)):
            return T_brenth
        elif T_secant is not None:
            return T_secant
        return T_brenth

        # return min(T_brenth, T_secant)



    # Default method
#    volume_solutions = volume_solutions_NR#volume_solutions_numpy#volume_solutions_NR
#    volume_solutions = staticmethod(volume_solutions_numpy)
#    volume_solutions = volume_solutions_fast
#    volume_solutions = staticmethod(volume_solutions_Cardano)
    volume_solutions = staticmethod(volume_solutions_halley)
#    volume_solutions = staticmethod(volume_solutions_doubledouble_float)

    volume_solutions_mp = staticmethod(volume_solutions_mpmath)

    # Solver which actually has the roots
    volume_solutions_full = staticmethod(volume_solutions_NR)

#    volume_solutions = volume_solutions_mpmath_float

    @property
    def mpmath_volumes(self):
        r'''Method to calculate to a high precision the exact roots to the
        cubic equation, using `mpmath`.

        Returns
        -------
        Vs : tuple[mpf]
            3 Real or not real volumes as calculated by `mpmath`, [m^3/mol]

        Notes
        -----

        Examples
        --------
        >>> eos = PRTranslatedTwu(T=300, P=1e5, Tc=512.5, Pc=8084000.0, omega=0.559, alpha_coeffs=(0.694911, 0.9199, 1.7), c=-1e-6)
        >>> eos.mpmath_volumes
        (mpf('0.0000489261705320261435106226558966745'), mpf('0.000541508154451321441068958547812526'), mpf('0.0243149463942697410611501615357228'))
        '''
        return volume_solutions_mpmath(self.T, self.P, self.b, self.delta, self.epsilon, self.a_alpha)

    @property
    def mpmath_volumes_float(self):
        r'''Method to calculate real roots of a cubic equation, using `mpmath`,
        but returned as floats.

        Returns
        -------
        Vs : list[float]
            All volumes calculated by `mpmath`, [m^3/mol]

        Notes
        -----

        Examples
        --------
        >>> eos = PRTranslatedTwu(T=300, P=1e5, Tc=512.5, Pc=8084000.0, omega=0.559, alpha_coeffs=(0.694911, 0.9199, 1.7), c=-1e-6)
        >>> eos.mpmath_volumes_float
        ((4.892617053202614e-05+0j), (0.0005415081544513214+0j), (0.024314946394269742+0j))
        '''
        return volume_solutions_mpmath_float(self.T, self.P, self.b, self.delta, self.epsilon, self.a_alpha)

    @property
    def mpmath_volume_ratios(self):
        r'''Method to compare, as ratios, the volumes of the implemented
        cubic solver versus those calculated using `mpmath`.

        Returns
        -------
        ratios : list[mpc]
            Either 1 or 3 volume ratios as calculated by `mpmath`, [-]

        Notes
        -----

        Examples
        --------
        >>> eos = PRTranslatedTwu(T=300, P=1e5, Tc=512.5, Pc=8084000.0, omega=0.559, alpha_coeffs=(0.694911, 0.9199, 1.7), c=-1e-6)
        >>> eos.mpmath_volume_ratios
        (mpc(real='0.99999999999999995', imag='0.0'), mpc(real='0.999999999999999965', imag='0.0'), mpc(real='1.00000000000000005', imag='0.0'))
        '''
        return tuple(i/j for i, j in zip(self.sorted_volumes, self.mpmath_volumes))

    def Vs_mpmath(self):
        r'''Method to calculate real roots of a cubic equation, using `mpmath`.

        Returns
        -------
        Vs : list[mpf]
            Either 1 or 3 real volumes as calculated by `mpmath`, [m^3/mol]

        Notes
        -----

        Examples
        --------
        >>> eos = PRTranslatedTwu(T=300, P=1e5, Tc=512.5, Pc=8084000.0, omega=0.559, alpha_coeffs=(0.694911, 0.9199, 1.7), c=-1e-6)
        >>> eos.Vs_mpmath()
        [mpf('0.0000489261705320261435106226558966745'), mpf('0.000541508154451321441068958547812526'), mpf('0.0243149463942697410611501615357228')]
        '''
        Vs = self.mpmath_volumes
        good_roots = [i.real for i in Vs if (i.real > 0.0 and abs(i.imag/i.real) < 1E-12)]
        good_roots.sort()
        return good_roots


    def volume_error(self):
        r'''Method to calculate the relative absolute error in the calculated
        molar volumes. This is computed with `mpmath`. If the number of real
        roots is different between mpmath and the implemented solver, an
        error of 1 is returned.

        Parameters
        ----------
        T : float
            Temperature, [K]

        Returns
        -------
        error : float
            relative absolute error in molar volumes , [-]

        Notes
        -----

        Examples
        --------

        >>> eos = PRTranslatedTwu(T=300, P=1e5, Tc=512.5, Pc=8084000.0, omega=0.559, alpha_coeffs=(0.694911, 0.9199, 1.7), c=-1e-6)
        >>> eos.volume_error()
        5.2192e-17
        '''
#        Vs_good, Vs = self.mpmath_volumes, self.sorted_volumes
        # Compare the reals only if mpmath has the imaginary roots
        Vs_good = self.volume_solutions_mp(self.T, self.P, self.b, self.delta, self.epsilon, self.a_alpha)
        Vs_filtered = [i.real for i in Vs_good if (i.real ==0 or abs(i.imag/i.real) < 1E-20) and i.real > self.b]
        if len(Vs_filtered) in (2, 3):
            two_roots_mpmath = True
            Vl_mpmath, Vg_mpmath = min(Vs_filtered), max(Vs_filtered)
        else:
            if hasattr(self, 'V_l') and hasattr(self, 'V_g'):
                # Wrong number of roots!
                return 1
            elif hasattr(self, 'V_l'):
                Vl_mpmath = Vs_filtered[0]
            elif hasattr(self, 'V_g'):
                Vg_mpmath = Vs_filtered[0]
            two_roots_mpmath = False
        err = 0

        if two_roots_mpmath:
            if (not hasattr(self, 'V_l') or not hasattr(self, 'V_g')):
                return 1.0

        # Important not to confuse the roots and also to not consider the third root
        try:
            Vl = self.V_l
            err_i = abs((Vl - Vl_mpmath)/Vl_mpmath)
            if err_i > err:
                err = err_i
        except:
            pass
        try:
            Vg = self.V_g
            err_i = abs((Vg - Vg_mpmath)/Vg_mpmath)
            if err_i > err:
                err = err_i
        except:
            pass
        return float(err)

    def _mpmath_volume_matching(self, V):
        '''Helper method which, given one of the three molar volume solutions
        of the EOS, returns the mpmath molar volume which is nearest it.
        '''
        Vs = self.mpmath_volumes
        rel_diffs = []

        for Vi in Vs:
            err = abs(Vi.real - V.real) + abs(Vi.imag - V.imag)
            rel_diffs.append(err)
        return Vs[rel_diffs.index(min(rel_diffs))]

    @property
    def V_l_mpmath(self):
        r'''The molar volume of the liquid phase calculated with `mpmath` to
        a higher precision, [m^3/mol]. This is useful for validating the
        cubic root solver(s). It is not quite a true arbitrary solution to the
        EOS, because the constants `b`,`epsilon`, `delta` and `a_alpha` as well
        as the input arguments `T` and `P` are not calculated with arbitrary
        precision. This is a feature when comparing the volume solution
        algorithms however as they work with the same finite-precision
        variables.
        '''
        if not hasattr(self, 'V_l'):
            raise ValueError("Not solved for that volume")
        return self._mpmath_volume_matching(self.V_l)

    @property
    def V_g_mpmath(self):
        r'''The molar volume of the gas phase calculated with `mpmath` to
        a higher precision, [m^3/mol]. This is useful for validating the
        cubic root solver(s). It is not quite a true arbitrary solution to the
        EOS, because the constants `b`,`epsilon`, `delta` and `a_alpha` as well
        as the input arguments `T` and `P` are not calculated with arbitrary
        precision. This is a feature when comparing the volume solution
        algorithms however as they work with the same finite-precision
        variables.
        '''
        if not hasattr(self, 'V_g'):
            raise ValueError("Not solved for that volume")
        return self._mpmath_volume_matching(self.V_g)

#    def fugacities_mpmath(self, dps=30):
#        # At one point thought maybe the fugacity equation was the source of error.
#        # No. always the volume equation.
#        import mpmath as mp
#        mp.mp.dps = dps
#        R_mp = mp.mpf(R)
#        b, T, P, epsilon, delta, a_alpha = self.b, self.T, self.P, self.epsilon, self.delta, self.a_alpha
#        b, T, P, epsilon, delta, a_alpha = [mp.mpf(i) for i in [b, T, P, epsilon, delta, a_alpha]]
#
#        Vs_good = volume_solutions_mpmath(self.T, self.P, self.b, self.delta, self.epsilon, self.a_alpha)
#        Vs_filtered = [i.real for i in Vs_good if (i.real == 0 or abs(i.imag/i.real) < 1E-20) and i.real > self.b]
#
#        if len(Vs_filtered) in (2, 3):
#            Vs = min(Vs_filtered), max(Vs_filtered)
#        else:
#            if hasattr(self, 'V_l') and hasattr(self, 'V_g'):
#                # Wrong number of roots!
#                raise ValueError("Error")
#            Vs = Vs_filtered
##            elif hasattr(self, 'V_l'):
##                Vs = Vs_filtered[0]
##            elif hasattr(self, 'V_g'):
##                Vg_mpmath = Vs_filtered[0]
#
#        log, exp, atanh, sqrt = mp.log, mp.exp, mp.atanh, mp.sqrt
#
#        return [P*exp((P*V + R_mp*T*log(V) - R_mp*T*log(P*V/(R_mp*T)) - R_mp*T*log(V - b)
#                       - R_mp*T - 2*a_alpha*atanh(2*V/sqrt(delta**2 - 4*epsilon)
#                       + delta/sqrt(delta**2 - 4*epsilon)).real/sqrt(delta**2 - 4*epsilon))/(R_mp*T))
#                for V in Vs]



    def volume_errors(self, Tmin=1e-4, Tmax=1e4, Pmin=1e-2, Pmax=1e9,
                      pts=50, plot=False, show=False, trunc_err_low=1e-18,
                      trunc_err_high=1.0, color_map=None, timing=False):
        r'''Method to create a plot of the relative absolute error in the
        cubic volume solution as compared to a higher-precision calculation.
        This method is incredible valuable for the development of more reliable
        floating-point based cubic solutions.

        Parameters
        ----------
        Tmin : float
            Minimum temperature of calculation, [K]
        Tmax : float
            Maximum temperature of calculation, [K]
        Pmin : float
            Minimum pressure of calculation, [Pa]
        Pmax : float
            Maximum pressure of calculation, [Pa]
        pts : int, optional
            The number of points to include in both the `x` and `y` axis;
            the validation calculation is slow, so increasing this too much
            is not advisable, [-]
        plot : bool
            If False, the calculated errors are returned without plotting
            the data, [-]
        show : bool
            Whether or not the plot should be rendered and shown; a handle to
            it is returned if `plot` is True for other purposes such as saving
            the plot to a file, [-]
        trunc_err_low : float
            Minimum plotted error; values under this are rounded to 0, [-]
        trunc_err_high : float
            Maximum plotted error; values above this are rounded to 1, [-]
        color_map : matplotlib.cm.ListedColormap
            Matplotlib colormap object, [-]
        timing : bool
            If True, plots the time taken by the volume root calculations
            themselves; this can reveal whether the solvers are taking fast or
            slow paths quickly, [-]

        Returns
        -------
        errors : list[list[float]]
            Relative absolute errors in the volume calculation (or timings in
            seconds if `timing` is True), [-]
        fig : matplotlib.figure.Figure
            Plotted figure, only returned if `plot` is True, [-]
        '''
        if timing:
            try:
                from time import perf_counter
            except:
                from time import clock as perf_counter
        Ts = logspace(log10(Tmin), log10(Tmax), pts)
        Ps = logspace(log10(Pmin), log10(Pmax), pts)
        kwargs = {}
        if hasattr(self, 'zs'):
            kwargs['zs'] = self.zs
            kwargs['fugacities'] = False

        errs = []
        for T in Ts:
            err_row = []
            for P in Ps:
                kwargs['T'] = T
                kwargs['P'] = P
                try:
                    obj = self.to(**kwargs)
                except Exception as e:
                    print('Failed to go to point, kwargs=%s with exception %s' %(kwargs, e))
                    # So bad we failed to calculate a real point
                    val = 1.0
                if timing:
                    t0 = perf_counter()
                    obj.volume_solutions(obj.T, obj.P, obj.b, obj.delta, obj.epsilon, obj.a_alpha)
                    val = perf_counter() - t0
                else:
                    val = float(obj.volume_error())
                    if val > 1e-7:
                        print([obj.T, obj.P, obj.b, obj.delta, obj.epsilon, obj.a_alpha, 'coordinates of failure', obj])
                err_row.append(val)
            errs.append(err_row)

        if plot:
            import matplotlib.pyplot as plt
            from matplotlib import ticker, cm
            from matplotlib.colors import LogNorm
            X, Y = np.meshgrid(Ts, Ps)
            z = np.array(errs).T
            fig, ax = plt.subplots()
            if not timing:
                if trunc_err_low is not None:
                    z[np.where(abs(z) < trunc_err_low)] = trunc_err_low
                if trunc_err_high is not None:
                    z[np.where(abs(z) > trunc_err_high)] = trunc_err_high

            if color_map is None:
                color_map = cm.viridis

            if not timing:
                norm = LogNorm(vmin=trunc_err_low, vmax=trunc_err_high)
            else:
                z *= 1e-6
                norm = None
            im = ax.pcolormesh(X, Y, z, cmap=color_map, norm=norm)
            cbar = fig.colorbar(im, ax=ax)
            if timing:
                cbar.set_label('Time [us]')
            else:
                cbar.set_label('Relative error')

            ax.set_yscale('log')
            ax.set_xscale('log')
            ax.set_xlabel('T [K]')
            ax.set_ylabel('P [Pa]')

            max_err = np.max(errs)
            if trunc_err_low is not None and max_err < trunc_err_low:
                max_err = 0
            if trunc_err_high is not None and max_err > trunc_err_high:
                max_err = trunc_err_high

            if timing:
                ax.set_title('Volume timings; max %.2e us' %(max_err*1e6))
            else:
                ax.set_title('Volume solution validation; max err %.4e' %(max_err))
            if show:
                plt.show()

            return errs, fig
        else:
            return errs

    def PT_surface_special(self, Tmin=1e-4, Tmax=1e4, Pmin=1e-2, Pmax=1e9,
                      pts=50, show=False, color_map=None,
                      mechanical=True, pseudo_critical=True, Psat=True,
                      determinant_zeros=True, phase_ID_transition=True,
                      base_property='V', base_min=None, base_max=None,
                      base_selection='Gmin'):
        r'''Method to create a plot of the special curves of a fluid -
        vapor pressure, determinant zeros, pseudo critical point,
        and mechanical critical point.

        The color background is a plot of the molar volume (by default) which
        has the minimum Gibbs energy (by default). If shown with a sufficient
        number of points, the curve between vapor and liquid should be shown
        smoothly.

        Parameters
        ----------
        Tmin : float, optional
            Minimum temperature of calculation, [K]
        Tmax : float, optional
            Maximum temperature of calculation, [K]
        Pmin : float, optional
            Minimum pressure of calculation, [Pa]
        Pmax : float, optional
            Maximum pressure of calculation, [Pa]
        pts : int, optional
            The number of points to include in both the `x` and `y` axis [-]
        show : bool, optional
            Whether or not the plot should be rendered and shown; a handle to
            it is returned if `plot` is True for other purposes such as saving
            the plot to a file, [-]
        color_map : matplotlib.cm.ListedColormap, optional
            Matplotlib colormap object, [-]
        mechanical : bool, optional
            Whether or not to include the mechanical critical point; this is
            the same as the critical point for a pure compound but not for a
            mixture, [-]
        pseudo_critical : bool, optional
            Whether or not to include the pseudo critical point; this is
            the same as the critical point for a pure compound but not for a
            mixture, [-]
        Psat : bool, optional
            Whether or not to include the vapor pressure curve; for mixtures
            this is neither the bubble nor dew curve, but rather a hypothetical
            one which uses the same equation as the pure components, [-]
        determinant_zeros : bool, optional
            Whether or not to include a curve showing when the EOS's
            determinant hits zero, [-]
        phase_ID_transition : bool, optional
            Whether or not to show a curve of where the PIP hits 1 exactly, [-]
        base_property : str, optional
            The property which should be plotted; '_l' and '_g' are added
            automatically according to the selected phase, [-]
        base_min : float, optional
            If specified, the `base` property will values will be limited to
            this value at the minimum, [-]
        base_max : float, optional
            If specified, the `base` property will values will be limited to
            this value at the maximum, [-]
        base_selection : str, optional
            For the base property, there are often two possible phases and but
            only one value can be plotted; use 'l' to pefer liquid-like values,
            'g' to prefer gas-like values, and 'Gmin' to prefer values of the
            phase with the lowest Gibbs energy, [-]


        Returns
        -------
        fig : matplotlib.figure.Figure
            Plotted figure, only returned if `plot` is True, [-]
        '''
        Ts = logspace(log10(Tmin), log10(Tmax), pts)
        Ps = logspace(log10(Pmin), log10(Pmax), pts)
        kwargs = {}
        if hasattr(self, 'zs'):
            kwargs['zs'] = self.zs

        l_prop = base_property + '_l'
        g_prop = base_property + '_g'
        base_positive = True

        # Are we an ideal-gas?
        if self.Zc == 1.0:
            phase_ID_transition = False
            Psat = False

        Vs = []
        for T in Ts:
            V_row = []
            for P in Ps:
                kwargs['T'] = T
                kwargs['P'] = P
                obj = self.to(**kwargs)
                if obj.phase == 'l/g':
                    if base_selection == 'Gmin':
                        V = getattr(obj, l_prop) if obj.G_dep_l < obj.G_dep_g else getattr(obj, g_prop)
                    elif base_selection == 'l':
                        V = getattr(obj, l_prop)
                    elif base_selection == 'g':
                        V = getattr(obj, g_prop)
                    else:
                        raise ValueError("Unknown value for base_selection")
                elif obj.phase == 'l':
                    V = getattr(obj, l_prop)
                else:
                    V = getattr(obj, g_prop)
                if base_max is not None and V > base_max: V = base_max
                if base_min is not None and V < base_min: V = base_min
                V_row.append(V)
                base_positive = base_positive and V > 0.0
            Vs.append(V_row)

        if self.multicomponent:
            Tc, Pc = self.pseudo_Tc, self.pseudo_Pc
        else:
            Tc, Pc = self.Tc, self.Pc

        if Psat:
            Pmax_Psat = min(Pc, Pmax)
            Pmin_Psat = max(1e-20, Pmin)
            Tmin_Psat, Tmax_Psat = self.Tsat(Pmin_Psat), self.Tsat(Pmax_Psat)
            if Tmin_Psat < Tmin or Tmin_Psat > Tmax: Tmin_Psat = Tmin
            if Tmax_Psat > Tmax or Tmax_Psat < Tmin: Tmax_Psat = Tmax

            Ts_Psats = []
            Psats = []
            for T in linspace(Tmin_Psat, Tmax_Psat, pts):
                P = self.Psat(T)
                Ts_Psats.append(T)
                Psats.append(P)
        if phase_ID_transition:
            Pmin_Psat = max(1e-20, Pmin)
            Tmin_ID = self.Tsat(Pmin_Psat)
            Tmax_ID = Tmax
            phase_ID_Ts = linspace(Tmin_ID, Tmax_ID, pts)
            low_P_limit = min(1e-4, Pmin)
            phase_ID_Ps = [self.P_PIP_transition(T, low_P_limit=low_P_limit)
            for T in phase_ID_Ts]


        if mechanical:
            if self.multicomponent:
                TP_mechanical = self.mechanical_critical_point()
            else:
                TP_mechanical = (Tc, Pc)

        if determinant_zeros:
            lows_det_Ps, high_det_Ps, Ts_dets_low, Ts_dets_high = [], [], [], []
            for T in Ts:
                a_alpha = self.a_alpha_and_derivatives(T, full=False)
                P_dets = self.P_discriminant_zeros_analytical(T=T, b=self.b, delta=self.delta,
                                                              epsilon=self.epsilon, a_alpha=a_alpha, valid=True)
                if P_dets:
                    P_det_min = min(P_dets)
                    P_det_max = max(P_dets)
                    if Pmin <= P_det_min <= Pmax:
                        lows_det_Ps.append(P_det_min)
                        Ts_dets_low.append(T)

                    if Pmin <= P_det_max <= Pmax:
                        high_det_Ps.append(P_det_max)
                        Ts_dets_high.append(T)


#        if plot:
        import matplotlib.pyplot as plt
        from matplotlib import ticker, cm
        from matplotlib.colors import LogNorm
        X, Y = np.meshgrid(Ts, Ps)
        z = np.array(Vs).T
        fig, ax = plt.subplots()
        if color_map is None:
            color_map = cm.viridis

        norm = LogNorm() if base_positive else None
        im = ax.pcolormesh(X, Y, z, cmap=color_map, norm=norm)
        cbar = fig.colorbar(im, ax=ax)
        cbar.set_label('%s' %base_property)

        if Psat:
            plt.plot(Ts_Psats, Psats, label='Psat')

        if determinant_zeros:
            plt.plot(Ts_dets_low, lows_det_Ps, label='Low trans')
            plt.plot(Ts_dets_high, high_det_Ps, label='High trans')

        if pseudo_critical:
            plt.plot([Tc], [Pc], 'x', label='Pseudo crit')
        if mechanical:
            plt.plot([TP_mechanical[0]], [TP_mechanical[1]], 'o', label='Mechanical')
        if phase_ID_transition:
            plt.plot(phase_ID_Ts, phase_ID_Ps, label='PIP=1')

        ax.set_yscale('log')
        ax.set_xscale('log')
        ax.set_xlabel('T [K]')
        ax.set_ylabel('P [Pa]')

        if (Psat or determinant_zeros or pseudo_critical or mechanical
            or phase_ID_transition):
            plt.legend()


        ax.set_title('%s vs minimum Gibbs validation' %(base_property))
        if show:
            plt.show()

        return fig

    def saturation_prop_plot(self, prop, Tmin=None, Tmax=None, pts=100,
                             plot=False, show=False, both=False):
        r'''Method to create a plot of a specified property of the EOS along
        the (pure component) saturation line.

        Parameters
        ----------
        prop : str
            Property to be used; such as 'H_dep_l' ( when `both` is False)
            or 'H_dep' (when `both` is True), [-]
        Tmin : float
            Minimum temperature of calculation; if this is too low the
            saturation routines will stop converging, [K]
        Tmax : float
            Maximum temperature of calculation; cannot be above the critical
            temperature, [K]
        pts : int, optional
            The number of temperature points to include [-]
        plot : bool
            If False, the calculated values and temperatures are returned
            without plotting the data, [-]
        show : bool
            Whether or not the plot should be rendered and shown; a handle to
            it is returned if `plot` is True for other purposes such as saving
            the plot to a file, [-]
        both : bool
            When true, append '_l' and '_g' and draw both the liquid and vapor
            property specified and return two different sets of values.

        Returns
        -------
        Ts : list[float]
            Logarithmically spaced temperatures in specified range, [K]
        props : list[float]
            The property specified if `both` is False; otherwise, the liquid
            properties, [various]
        props_g : list[float]
            The gas properties, only returned if `both` is True, [various]
        fig : matplotlib.figure.Figure
            Plotted figure, only returned if `plot` is True, [-]
        '''
        if Tmax is None:
            if self.multicomponent:
                Tmax = self.pseudo_Tc
            else:
                Tmax = self.Tc
        if Tmin is None:
            Tmin = self.Tsat(1e-5)


        Ts = logspace(log10(Tmin), log10(Tmax), pts)
        kwargs = {}
        if hasattr(self, 'zs'):
            kwargs['zs'] = self.zs
        props = []
        if both:
            props2 = []
            prop_l = prop + '_l'
            prop_g = prop + '_g'

        for T in Ts:
            kwargs['T'] = T
            kwargs['P'] = self.Psat(T)
            obj = self.to(**kwargs)
            if both:
                v = getattr(obj, prop_l)
                try:
                    v = v()
                except:
                    pass
                props.append(v)

                v = getattr(obj, prop_g)
                try:
                    v = v()
                except:
                    pass
                props2.append(v)
            else:
                v = getattr(obj, prop)
                try:
                    v = v()
                except:
                    pass
                props.append(v)

        if plot:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots()

            if both:
                plt.plot(Ts, props, label='Liquid')
                plt.plot(Ts, props2, label='Gas')
                plt.legend()
            else:
                plt.plot(Ts, props)

            ax.set_xlabel('Temperature [K]')
            ax.set_ylabel(r'%s' %(prop))


            ax.set_title(r'Saturation %s curve' %(prop))
            if show:
                plt.show()

            if both:
                return Ts, props, props2, fig
            return Ts, props, fig
        if both:
            return Ts, props, props2
        return Ts, props

    def Psat_errors(self, Tmin=None, Tmax=None, pts=50, plot=False, show=False,
                    trunc_err_low=1e-18, trunc_err_high=1.0, Pmin=1e-100):
        r'''Method to create a plot of vapor pressure and the relative error
        of its calculation vs. the iterative `polish` approach.

        Parameters
        ----------
        Tmin : float
            Minimum temperature of calculation; if this is too low the
            saturation routines will stop converging, [K]
        Tmax : float
            Maximum temperature of calculation; cannot be above the critical
            temperature, [K]
        pts : int, optional
            The number of temperature points to include [-]
        plot : bool
            If False, the solution is returned without plotting the data, [-]
        show : bool
            Whether or not the plot should be rendered and shown; a handle to
            it is returned if `plot` is True for other purposes such as saving
            the plot to a file, [-]
        trunc_err_low : float
            Minimum plotted error; values under this are rounded to 0, [-]
        trunc_err_high : float
            Maximum plotted error; values above this are rounded to 1, [-]
        Pmin : float
            Minimum pressure for the solution to work on, [Pa]

        Returns
        -------
        errors : list[float]
            Absolute relative errors, [-]
        Psats_num : list[float]
            Vapor pressures calculated to full precision, [Pa]
        Psats_fit : list[float]
            Vapor pressures calculated with the fast solution, [Pa]
        fig : matplotlib.figure.Figure
            Plotted figure, only returned if `plot` is True, [-]
        '''
        try:
            Tc = self.Tc
        except:
            Tc = self.pseudo_Tc


        if Tmax is None:
            Tmax = Tc
        if Tmin is None:
            Tmin = .1*Tc

        try:
            # Can we get the direct temperature for Pmin
            if Pmin is not None:
                Tmin_Pmin = self.Tsat(P=Pmin, polish=True)
        except:
            Tmin_Pmin = None

        if Tmin_Pmin is not None:
            Tmin = max(Tmin, Tmin_Pmin)

        Ts = logspace(log10(Tmin), log10(Tmax), int(pts/3))
        Ts[-1] = Tmax

        Ts_mid = linspace(Tmin, Tmax, int(pts/3))

        Ts_high = linspace(Tmax*.99, Tmax, int(pts/3))
        Ts = list(sorted(Ts_high + Ts + Ts_mid))



        Ts_worked, Psats_num, Psats_fit = [], [], []
        for T in Ts:
            failed = False
            try:
                Psats_fit.append(self.Psat(T, polish=False))
            except NoSolutionError:
                # Trust the fit - do not continue if no good
                continue
            except Exception as e:
                raise ValueError("Failed to converge at %.16f K with unexpected error" %(T), e, self)

            try:
                Psat_polished = self.Psat(T, polish=True)
                Psats_num.append(Psat_polished)
            except Exception as e:
                failed = True
                raise ValueError("Failed to converge at %.16f K with unexpected error" %(T), e, self)

            Ts_worked.append(T)
        Ts = Ts_worked

        errs = np.array([abs(i-j)/i for i, j in zip(Psats_num, Psats_fit)])
        if plot:
            import matplotlib.pyplot as plt
            fig, ax1 = plt.subplots()
            ax2 = ax1.twinx()
            if trunc_err_low is not None:
                errs[np.where(abs(errs) < trunc_err_low)] = trunc_err_low
            if trunc_err_high is not None:
                errs[np.where(abs(errs) > trunc_err_high)] = trunc_err_high

            Trs = np.array(Ts)/Tc
            ax1.plot(Trs, errs)

            ax2.plot(Trs, Psats_num)
            ax2.plot(Trs, Psats_fit)
            ax1.set_yscale('log')
            ax1.set_xscale('log')

            ax2.set_yscale('log')
            ax2.set_xscale('log')

            ax1.set_xlabel('Tr [-]')
            ax1.set_ylabel('AARD [-]')

            ax2.set_ylabel('Psat [Pa]')

            max_err = np.max(errs)
            if trunc_err_low is not None and max_err < trunc_err_low:
                max_err = 0
            if trunc_err_high is not None and max_err > trunc_err_high:
                max_err = trunc_err_high

            ax1.set_title('Vapor pressure validation; max rel err %.4e' %(max_err))
            if show:
                plt.show()

            return errs, Psats_num, Psats_fit, fig
        else:
            return errs, Psats_num, Psats_fit

#    def PIP_map(self, Tmin=1e-4, Tmax=1e4, Pmin=1e-2, Pmax=1e9,
#                pts=50, plot=False, show=False, color_map=None):
#        # TODO rename PIP_ID_map or add flag to change if it plots PIP or bools.
#        # TODO add doc
#        Ts = logspace(log10(Tmin), log10(Tmax), pts)
#        Ps = logspace(log10(Pmin), log10(Pmax), pts)
#        kwargs = {}
#        if hasattr(self, 'zs'):
#            kwargs['zs'] = self.zs
#
#        PIPs = []
#        for T in Ts:
#            PIP_row = []
#            for P in Ps:
#                kwargs['T'] = T
#                kwargs['P'] = P
#                obj = self.to(**kwargs)
##                v = obj.discriminant
##                # need make negatives under 1, positive above 1
##                if v > 0.0:
##                    v = (1.0 + (1e10 - 1.0)/(1.0 + trunc_exp(-v)))
##                else:
##                    v = (1e-10 + (1.0 - 1e-10)/(1.0 + trunc_exp(-v)))
#
#                if obj.phase == 'l/g':
#                    v = 1
#                elif obj.phase == 'g':
#                    v = 0
#                elif obj.phase == 'l':
#                    v = 2
#                PIP_row.append(v)
#            PIPs.append(PIP_row)
#
#        if plot:
#            import matplotlib.pyplot as plt
#            from matplotlib import ticker, cm
#            from matplotlib.colors import LogNorm
#            X, Y = np.meshgrid(Ts, Ps)
#            z = np.array(PIPs).T
#            fig, ax = plt.subplots()
#            if color_map is None:
#                color_map = cm.viridis
#
#            im = ax.pcolormesh(X, Y, z, cmap=color_map,
##                               norm=LogNorm(vmin=1e-10, vmax=1e10)
#                               )
#            cbar = fig.colorbar(im, ax=ax)
#            cbar.set_label('PIP')
#
#            ax.set_yscale('log')
#            ax.set_xscale('log')
#            ax.set_xlabel('T [K]')
#            ax.set_ylabel('P [Pa]')
#
#
#            ax.set_title('Volume root/phase ID validation')
#            if show:
#                plt.show()
#
#            return PIPs, fig

    def derivatives_and_departures(self, T, P, V, b, delta, epsilon, a_alpha, da_alpha_dT, d2a_alpha_dT2, quick=True):

        dP_dT, dP_dV, d2P_dT2, d2P_dV2, d2P_dTdV, H_dep, S_dep, Cv_dep = (
        self.main_derivatives_and_departures(T, P, V, b, delta, epsilon,
                                             a_alpha, da_alpha_dT,
                                             d2a_alpha_dT2))
        try:
            dV_dP = 1.0/dP_dV
        except:
            dV_dP = inf
        dT_dP = 1./dP_dT

        dV_dT = -dP_dT*dV_dP
        dT_dV = 1./dV_dT


        dV_dP2 = dV_dP*dV_dP
        dV_dP3 = dV_dP*dV_dP2

        inverse_dP_dT2 = dT_dP*dT_dP
        inverse_dP_dT3 = inverse_dP_dT2*dT_dP

        d2V_dP2 = -d2P_dV2*dV_dP3 # unused
        d2T_dP2 = -d2P_dT2*inverse_dP_dT3 # unused

        d2T_dV2 = (-(d2P_dV2*dP_dT - dP_dV*d2P_dTdV)*inverse_dP_dT2
                   +(d2P_dTdV*dP_dT - dP_dV*d2P_dT2)*inverse_dP_dT3*dP_dV) # unused
        d2V_dT2 = (-(d2P_dT2*dP_dV - dP_dT*d2P_dTdV)*dV_dP2 # unused
                   +(d2P_dTdV*dP_dV - dP_dT*d2P_dV2)*dV_dP3*dP_dT)

        d2V_dPdT = -(d2P_dTdV*dP_dV - dP_dT*d2P_dV2)*dV_dP3 # unused
        d2T_dPdV = -(d2P_dTdV*dP_dT - dP_dV*d2P_dT2)*inverse_dP_dT3 # unused

        return (dP_dT, dP_dV, dV_dT, dV_dP, dT_dV, dT_dP,
                d2P_dT2, d2P_dV2, d2V_dT2, d2V_dP2, d2T_dV2, d2T_dP2,
                d2V_dPdT, d2P_dTdV, d2T_dPdV, # d2P_dTdV is used
                H_dep, S_dep, Cv_dep)



    @property
    def sorted_volumes(self):
        r'''List of lexicographically-sorted molar volumes available from the
        root finding algorithm used to solve the PT point. The convention of
        sorting lexicographically comes from numpy's handling of complex
        numbers, which python does not define. This method was added to
        facilitate testing, as the volume solution method changes over time
        and the ordering does as well.

        Examples
        --------
        >>> PR(Tc=507.6, Pc=3025000, omega=0.2975, T=299., P=1E6).sorted_volumes
        ((0.000130222125139+0j), (0.00112363131346-0.00129269672343j), (0.00112363131346+0.00129269672343j))
        '''
        sort_fun = lambda x: (x.real, x.imag)
        full_volumes = self.volume_solutions_full(self.T, self.P, self.b, self.delta, self.epsilon, self.a_alpha)
        full_volumes = [i + 0.0j for i in full_volumes]
        return tuple(sorted(full_volumes, key=sort_fun))


    def Tsat(self, P, polish=False):
        r'''Generic method to calculate the temperature for a specified
        vapor pressure of the pure fluid.
        This is simply a bounded solver running between `0.2Tc` and `Tc` on the
        `Psat` method.

        Parameters
        ----------
        P : float
            Vapor pressure, [Pa]
        polish : bool, optional
            Whether to attempt to use a numerical solver to make the solution
            more precise or not

        Returns
        -------
        Tsat : float
            Temperature of saturation, [K]

        Notes
        -----
        It is recommended not to run with `polish=True`, as that will make the
        calculation much slower.
        '''
        fprime = False
        global curr_err

        def to_solve_newton(T):
            global curr_err
            assert T > 0.0
            e = self.to_TP(T, P)
            try:
                fugacity_l = e.fugacity_l
            except AttributeError as err:
                raise err
            try:
                fugacity_g = e.fugacity_g
            except AttributeError as err:
                raise err

            curr_err = fugacity_l - fugacity_g
            if fprime:
                d_err_d_T = e.dfugacity_dT_l - e.dfugacity_dT_g
                return curr_err, d_err_d_T

            # print('err', err, 'rel err', err/T, 'd_err_d_T', d_err_d_T, 'T', T)

            return curr_err

        logP = log(P)
        def to_solve(T):
            global curr_err
            if fprime:
                dPsat_dT, Psat = self.dPsat_dT(T, polish=polish, also_Psat=True)
                curr_err = Psat - P

                # Log translation - tends to save a few iterations
                err_trans = log(Psat) - logP
                return err_trans, dPsat_dT/Psat
#                return curr_err, derr_dT
            curr_err = self.Psat(T, polish=polish) - P
            return curr_err#, derr_dT
#            return copysign(log(abs(err)), err)
        # Outstanding improvements to do: Better guess; get NR working;
        # see if there is a general curve

        try:
            Tc, Pc = self.Tc, self.Pc
        except:
            Tc, Pc = self.pseudo_Tc, self.pseudo_Pc

        guess = -5.4*Tc/(1.0*log(P/Pc) - 5.4)
        high = guess*2.0
        low = guess*0.5
#        return newton(to_solve, guess, fprime=True, ytol=1e-6, high=self.Pc)
#        return newton(to_solve, guess, ytol=1e-6, high=self.Pc)

        # Methanol is a good example of why 1.5 is needed
        low_hope, high_hope = max(guess*.5, 0.2*Tc), min(Tc, guess*1.5)


        try:
            err_low, err_high = to_solve(low_hope), to_solve(high_hope)
            if err_low*err_high < 0.0:
                if guess < low_hope or guess > high_hope:
                    guess = 0.5*(low_hope + high_hope)
                fprime = True
                Tsat = newton(to_solve, guess, xtol=1.48e-10,fprime=True, low=low_hope, high=high_hope, bisection=True)
    #            fprime = False
    #            Tsat = brenth(to_solve, low_hope, high_hope)
                abs_rel_err = abs(curr_err)/P
                if abs_rel_err < 1e-9:
                    return Tsat
                elif abs_rel_err < 1e-2:
                    guess = Tsat
            else:
                try:
                    return brenth(to_solve, 0.2*Tc, Tc)
                except:
                    try:
                        return brenth(to_solve, 0.2*Tc, Tc*1.5)
                    except:
                        pass
        except:
            pass
        fprime = True

        try:
            try:
                Tsat = newton(to_solve_newton, guess, fprime=True, maxiter=100,
                              xtol=4e-13, require_eval=False, damping=1.0, low=Tc*1e-5)
            except:
                try:
                    Tsat = newton(to_solve_newton, guess, fprime=True, maxiter=100,
                                  xtol=4e-13, require_eval=False, damping=1.0, low=low, high=high)
                    assert Tsat != low and Tsat != high
                except:
                    Tsat = newton(to_solve_newton, guess, fprime=True, maxiter=250, # the wider range can take more iterations
                                  xtol=4e-13, require_eval=False, damping=1.0, low=low, high=high*2)
                    assert Tsat != low and Tsat != high*2
        except:
            # high = self.Tc
            # try:
            #     high = min(high, self.T_discriminant_zero_l()*(1-1e-8))
            # except:
            #     pass
            # Does not seem to be working
            try:
                Tsat = None
                Tsat = newton(to_solve_newton, guess, fprime=True, maxiter=200, high=high, low=low,
                              xtol=4e-13, require_eval=False, damping=1.0)
            except:
                pass
            fprime = False
            if Tsat is None or abs(to_solve_newton(Tsat)) == P:
                Tsat = brenth(to_solve_newton, low, high)

        return Tsat

    def Psat(self, T, polish=False, guess=None):
        r'''Generic method to calculate vapor pressure for a specified `T`.

        From Tc to 0.32Tc, uses a 10th order polynomial of the following form:

        .. math::
            \ln\frac{P_r}{T_r} = \sum_{k=0}^{10} C_k\left(\frac{\alpha}{T_r}
            -1\right)^{k}

        If `polish` is True, SciPy's `newton` solver is launched with the
        calculated vapor pressure as an initial guess in an attempt to get more
        accuracy. This may not converge however.

        Results above the critical temperature are meaningless. A first-order
        polynomial is used to extrapolate under 0.32 Tc; however, there is
        normally not a volume solution to the EOS which can produce that
        low of a pressure.

        Parameters
        ----------
        T : float
            Temperature, [K]
        polish : bool, optional
            Whether to attempt to use a numerical solver to make the solution
            more precise or not

        Returns
        -------
        Psat : float
            Vapor pressure, [Pa]

        Notes
        -----
        EOSs sharing the same `b`, `delta`, and `epsilon` have the same
        coefficient sets.

        Form for the regression is inspired from [1]_.

        No volume solution is needed when `polish=False`; the only external
        call is for the value of `a_alpha`.

        References
        ----------
        .. [1] Soave, G. "Direct Calculation of Pure-Compound Vapour Pressures
           through Cubic Equations of State." Fluid Phase Equilibria 31, no. 2
           (January 1, 1986): 203-7. doi:10.1016/0378-3812(86)90013-0.
        '''
        Tc, Pc = self.Tc, self.Pc
        if T == Tc:
            return Pc
        a_alpha = self.a_alpha_and_derivatives(T, full=False)
        alpha = a_alpha/self.a
        Tr = T/self.Tc
        x = alpha/Tr - 1.


        if Tr > 0.999 and not isinstance(self, RK):
            y = horner(self.Psat_coeffs_critical, x)
            Psat = y*Tr*Pc
            if Psat > Pc and T < Tc:
                Psat = Pc*(1.0 - 1e-14)
        else:
            # TWUPR/SRK TODO need to be prepared for x being way outside the range (in the weird direction - at the start)
            Psat_ranges_low = self.Psat_ranges_low
            if x > Psat_ranges_low[-1]:
                if not polish:
                    raise NoSolutionError("T %.8f K is too low for equations to converge" %(T))
                else:
                    # Needs to still be here for generating better data
                    x = Psat_ranges_low[-1]
                    polish = True

            for i in range(len(Psat_ranges_low)):
                if x < Psat_ranges_low[i]:
                    break
            y = 0.0
            for c in self.Psat_coeffs_low[i]:
                y = y*x + c

            try:
                Psat = exp(y)*Tr*Pc
                if Psat == 0.0:
                    if polish:
                        Psat = 1e-100
                    else:
                        raise NoSolutionError("T %.8f K is too low for equations to converge" %(T))
            except OverflowError:
                # coefficients sometimes overflow before T is lowered to 0.32Tr
                # For
                polish = True # There is no solution available to polish
                Psat = 1

        if polish:
            if T > Tc:
                raise ValueError("Cannot solve for equifugacity condition "
                                 "beyond critical temperature")
            if guess is not None:
                Psat = guess
            converged = False
            def to_solve_newton(P):
                # For use by newton. Only supports initialization with Tc, Pc and omega
                # ~200x slower and not guaranteed to converge (primary issue is one phase)
                # not existing
                assert P > 0.0
                e = self.to_TP(T, P)
                # print(e.volume_error(), e)
                try:
                    fugacity_l = e.fugacity_l
                except AttributeError as err:
                    # return 1000, 1000
                    raise err

                try:
                    fugacity_g = e.fugacity_g
                except AttributeError as err:
                    # return 1000, 1000
                    raise err

                err = fugacity_l - fugacity_g

                d_err_d_P = e.dfugacity_dP_l - e.dfugacity_dP_g # -1 for low pressure
                if isnan(d_err_d_P):
                    d_err_d_P = -1.0
                # print('err', err, 'rel err', err/P, 'd_err_d_P', d_err_d_P, 'P', P)
                # Clamp the derivative - if it will step to zero or negative, dampen to half the distance which gets to zero
                if (P - err/d_err_d_P) <= 0.0: # This is the one matching newton
                # if (P - err*d_err_d_P) <= 0.0:
                    d_err_d_P = -1.0001

                return err, d_err_d_P
            try:
                try:
                    boundaries = GCEOS.P_discriminant_zeros_analytical(T, self.b, self.delta, self.epsilon, a_alpha, valid=True)
                    low, high = min(boundaries), max(boundaries)
                except:
                    pass
                try:
                    high = self.P_discriminant_zero()
                except:
                    high = Pc


                # def damping_func(p0, step, damping):
                #     if step == 1:
                #         damping = damping*0.5
                #     p = p0 + step * damping
                #     return p

                Psat = newton(to_solve_newton, Psat, high=high, fprime=True, maxiter=100,
                              xtol=4e-13, require_eval=False, damping=1.0) #  ,ytol=1e-6*Psat # damping_func=damping_func
#                print(to_solve_newton(Psat), 'newton error')
                converged = True
            except:
                pass

            if not converged:
                def to_solve_bisect(P):
                    e = self.to_TP(T, P)
                    # print(e.volume_error(), e)
                    try:
                        fugacity_l = e.fugacity_l
                    except AttributeError as err:
                        return 1e20

                    try:
                        fugacity_g = e.fugacity_g
                    except AttributeError as err:
                        return -1e20
                    err = fugacity_l - fugacity_g
#                    print(err, 'err', 'P', P)
                    return err
                for low, high in zip([.98*Psat, 1, 1e-40, Pc*.9, Psat*.9999], [1.02*Psat, Pc, 1, Pc*1.000000001, Pc]):
                    try:
                        Psat = bisect(to_solve_bisect, low, high, ytol=1e-6*Psat, maxiter=128)
#                        print(to_solve_bisect(Psat), 'bisect error')
                        converged = True
                        break
                    except:
                        pass

            # Last ditch attempt
            if not converged:
                # raise ValueError("Could not converge")
                if Tr > 0.5:
                    # Near critical temperature issues
                    points = [Pc*f for f in linspace(1e-3, 1-1e-8, 50) + linspace(.9, 1-1e-8, 50)]
                    ytol = 1e-6*Psat
                else:
                    # Low temperature issues
                    points = [Psat*f for f in logspace(-5.5, 5.5, 16)]
                    # points = [Psat*f for f in logspace(-2.5, 2.5, 100)]
                    ytol = None # Cryogenic point unlikely to work to desired tolerance
                    # Work on point closer to Psat first
                    points.sort(key=lambda x: abs(log10(x)))
                low, high = None, None
                for point in points:
                    try:
                        err = to_solve_newton(point)[0] # Do not use bisect function as it does not raise errors
                        if err > 0.0:
                            high = point
                        elif err < 0.0:
                            low = point
                    except:
                        pass
                    if low is not None and high is not None:
                        # print('reached bisection')
                        Psat = brenth(to_solve_bisect, low, high, ytol=ytol, maxiter=128)
#                        print(to_solve_bisect(Psat), 'bisect error')
                        converged = True
                        break
                # print('tried all points')
                # Check that the fugacity error vs. Psat is OK
                if abs(to_solve_bisect(Psat)/Psat) > .0001:
                    converged = False

            if not converged:
                raise ValueError("Could not converge at T=%.6f K" %(T))

        return Psat


    def dPsat_dT(self, T, polish=False, also_Psat=False):
        r'''Generic method to calculate the temperature derivative of vapor
        pressure for a specified `T`. Implements the analytical derivative
        of the three polynomials described in `Psat`.

        As with `Psat`, results above the critical temperature are meaningless.
        The first-order polynomial which is used to calculate it under 0.32 Tc
        may not be physicall meaningful, due to there normally not being a
        volume solution to the EOS which can produce that low of a pressure.

        Parameters
        ----------
        T : float
            Temperature, [K]
        polish : bool, optional
            Whether to attempt to use a numerical solver to make the solution
            more precise or not
        also_Psat : bool, optional
            Calculating `dPsat_dT` necessarily involves calculating `Psat`;
            when this is set to True, a second return value is added, whic is
            the actual `Psat` value.

        Returns
        -------
        dPsat_dT : float
            Derivative of vapor pressure with respect to temperature, [Pa/K]
        Psat : float, returned if `also_Psat` is `True`
            Vapor pressure, [Pa]

        Notes
        -----
        There is a small step change at 0.32 Tc for all EOS due to the two
        switch between polynomials at that point.

        Useful for calculating enthalpy of vaporization with the Clausius
        Clapeyron Equation. Derived with SymPy's diff and cse.
        '''
        if polish:
            # Calculate the derivative of saturation pressure analytically
            Psat = self.Psat(T, polish=polish)
            sat_eos = self.to(T=T, P=Psat)
            dfg_T, dfl_T = sat_eos.dfugacity_dT_g, sat_eos.dfugacity_dT_l
            dfg_P, dfl_P = sat_eos.dfugacity_dP_g, sat_eos.dfugacity_dP_l
            dPsat_dT = (dfg_T - dfl_T)/(dfl_P - dfg_P)
            if also_Psat:
                return dPsat_dT, Psat
            return dPsat_dT

        a_alphas = self.a_alpha_and_derivatives(T)
        a_inv = 1.0/self.a
        try:
            Tc, Pc = self.Tc, self.Pc
        except:
            Tc, Pc = self.pseudo_Tc, self.pseudo_Pc

        alpha, d_alpha_dT = a_alphas[0]*a_inv, a_alphas[1]*a_inv
        Tc_inv = 1.0/Tc
        T_inv = 1.0/T
        Tr = T*Tc_inv
#        if Tr < 0.32 and not isinstance(self, PR):
#            # Delete
#            c = self.Psat_coeffs_limiting
#            return self.Pc*T*c[0]*(self.Tc*d_alpha_dT/T - self.Tc*alpha/(T*T)
#                              )*exp(c[0]*(-1. + self.Tc*alpha/T) + c[1]
#                              )/self.Tc + self.Pc*exp(c[0]*(-1.
#                              + self.Tc*alpha/T) + c[1])/self.Tc
        if Tr > 0.999 and not isinstance(self, RK):
            # OK
            x = alpha/Tr - 1.
            y = horner(self.Psat_coeffs_critical, x)
            dy_dT = T_inv*(Tc*d_alpha_dT - Tc*alpha*T_inv)*horner(self.Psat_coeffs_critical_der, x)
            dPsat_dT = Pc*(T*dy_dT*Tc_inv + y*Tc_inv)
            if also_Psat:
                Psat = y*Tr*Pc
                return dPsat_dT, Psat
            return dPsat_dT
        else:
            Psat_coeffs_low = self.Psat_coeffs_low
            Psat_ranges_low = self.Psat_ranges_low
            x = alpha/Tr - 1.
            if x > Psat_ranges_low[-1]:
                raise NoSolutionError("T %.8f K is too low for equations to converge" %(T))

            for i in range(len(Psat_ranges_low)):
                if x < Psat_ranges_low[i]:
                    break
            y, dy = 0.0, 0.0
            for c in Psat_coeffs_low[i]:
                dy = x*dy + y
                y = x*y + c

            exp_y = exp(y)
            dy_dT = Tc*T_inv*(d_alpha_dT - alpha*T_inv)*dy#horner_and_der(Psat_coeffs_low[i], x)[1]
            Psat = exp_y*Tr*Pc

            dPsat_dT = (T*dy_dT + 1.0)*Pc*exp_y*Tc_inv
            if also_Psat:
                return dPsat_dT, Psat
            return dPsat_dT


#            # change chebval to horner, and get new derivative
#            x = alpha/Tr - 1.
#            arg = (self.Psat_cheb_constant_factor[1]*(x + self.Psat_cheb_constant_factor[0]))
#            y = chebval(arg, self.Psat_cheb_coeffs)
#
#            exp_y = exp(y)
#            dy_dT = T_inv*(Tc*d_alpha_dT - Tc*alpha*T_inv)*chebval(arg,
#                     self.Psat_cheb_coeffs_der)*self.Psat_cheb_constant_factor[1]
#            Psat = Pc*T*exp_y*dy_dT*Tc_inv + Pc*exp_y*Tc_inv
#            return Psat

    def phi_sat(self, T, polish=True):
        r'''Method to calculate the saturation fugacity coefficient of the
        compound. This does not require solving the EOS itself.

        Parameters
        ----------
        T : float
            Temperature, [K]
        polish : bool, optional
            Whether to perform a rigorous calculation or to use a polynomial
            fit, [-]

        Returns
        -------
        phi_sat : float
            Fugacity coefficient along the liquid-vapor saturation line, [-]

        Notes
        -----
        Accuracy is generally around 1e-7. If Tr is under 0.32, the rigorous
        method is always used, but a solution may not exist if both phases
        cannot coexist. If Tr is above 1, likewise a solution does not exist.
        '''
        Tr = T/self.Tc
        if polish or not 0.32 <= Tr <= 1.0:
            e = self.to_TP(T=T, P=self.Psat(T, polish=True)) # True
            try:
                return e.phi_l
            except:
                return e.phi_g

        alpha = self.a_alpha_and_derivatives(T, full=False)/self.a
        x = alpha/Tr - 1.
        return horner(self.phi_sat_coeffs, x)

    def dphi_sat_dT(self, T, polish=True):
        r'''Method to calculate the temperature derivative of saturation
        fugacity coefficient of the
        compound. This does require solving the EOS itself.

        Parameters
        ----------
        T : float
            Temperature, [K]
        polish : bool, optional
            Whether to perform a rigorous calculation or to use a polynomial
            fit, [-]

        Returns
        -------
        dphi_sat_dT : float
            First temperature derivative of fugacity coefficient along the
            liquid-vapor saturation line, [1/K]

        Notes
        -----
        '''
        if T == self.Tc:
            T = (self.Tc*(1.0 - 1e-15))
        Psat = self.Psat(T, polish=polish)
        sat_eos = self.to(T=T, P=Psat)
        dfg_T, dfl_T = sat_eos.dfugacity_dT_g, sat_eos.dfugacity_dT_l
        dfg_P, dfl_P = sat_eos.dfugacity_dP_g, sat_eos.dfugacity_dP_l
        dPsat_dT = (dfg_T - dfl_T)/(dfl_P - dfg_P)

        fugacity = sat_eos.fugacity_l
        dfugacity_sat_dT = dPsat_dT*sat_eos.dfugacity_dP_l + sat_eos.dfugacity_dT_l

        Psat_inv = 1.0/Psat

        return (dfugacity_sat_dT - fugacity*dPsat_dT*Psat_inv)*Psat_inv

    def d2phi_sat_dT2(self, T, polish=True):
        r'''Method to calculate the second temperature derivative of saturation
        fugacity coefficient of the
        compound. This does require solving the EOS itself.

        Parameters
        ----------
        T : float
            Temperature, [K]
        polish : bool, optional
            Whether to perform a rigorous calculation or to use a polynomial
            fit, [-]

        Returns
        -------
        d2phi_sat_dT2 : float
            Second temperature derivative of fugacity coefficient along the
            liquid-vapor saturation line, [1/K^2]

        Notes
        -----
        This is presently a numerical calculation.
        '''
        return derivative(lambda T: self.dphi_sat_dT(T, polish=polish), T,
                          dx=T*1e-7, upper_limit=self.Tc)

    def V_l_sat(self, T):
        r'''Method to calculate molar volume of the liquid phase along the
        saturation line.

        Parameters
        ----------
        T : float
            Temperature, [K]

        Returns
        -------
        V_l_sat : float
            Liquid molar volume along the saturation line, [m^3/mol]

        Notes
        -----
        Computes `Psat`, and then uses `volume_solutions` to obtain the three
        possible molar volumes. The lowest value is returned.
        '''
        Psat = self.Psat(T)
        a_alpha = self.a_alpha_and_derivatives(T, full=False)
        Vs = self.volume_solutions(T, Psat, self.b, self.delta, self.epsilon, a_alpha)
        # Assume we can safely take the Vmax as gas, Vmin as l on the saturation line
        return min([i.real for i in Vs if i.real > self.b])

    def V_g_sat(self, T):
        r'''Method to calculate molar volume of the vapor phase along the
        saturation line.

        Parameters
        ----------
        T : float
            Temperature, [K]

        Returns
        -------
        V_g_sat : float
            Gas molar volume along the saturation line, [m^3/mol]

        Notes
        -----
        Computes `Psat`, and then uses `volume_solutions` to obtain the three
        possible molar volumes. The highest value is returned.
        '''
        Psat = self.Psat(T)
        a_alpha = self.a_alpha_and_derivatives(T, full=False)
        Vs = self.volume_solutions(T, Psat, self.b, self.delta, self.epsilon, a_alpha)
        # Assume we can safely take the Vmax as gas, Vmin as l on the saturation line
        return max([i.real for i in Vs])

    def Hvap(self, T):
        r'''Method to calculate enthalpy of vaporization for a pure fluid from
        an equation of state, without iteration.

        .. math::
            \frac{dP^{sat}}{dT}=\frac{\Delta H_{vap}}{T(V_g - V_l)}

        Results above the critical temperature are meaningless. A first-order
        polynomial is used to extrapolate under 0.32 Tc; however, there is
        normally not a volume solution to the EOS which can produce that
        low of a pressure.

        Parameters
        ----------
        T : float
            Temperature, [K]

        Returns
        -------
        Hvap : float
            Increase in enthalpy needed for vaporization of liquid phase along
            the saturation line, [J/mol]

        Notes
        -----
        Calculates vapor pressure and its derivative with `Psat` and `dPsat_dT`
        as well as molar volumes of the saturation liquid and vapor phase in
        the process.

        Very near the critical point this provides unrealistic results due to
        `Psat`'s polynomials being insufficiently accurate.

        References
        ----------
        .. [1] Walas, Stanley M. Phase Equilibria in Chemical Engineering.
           Butterworth-Heinemann, 1985.
        '''
        Psat = self.Psat(T)
        dPsat_dT = self.dPsat_dT(T)
        a_alpha = self.a_alpha_and_derivatives(T, full=False)
        Vs = self.volume_solutions(T, Psat, self.b, self.delta, self.epsilon, a_alpha)
        # Assume we can safely take the Vmax as gas, Vmin as l on the saturation line
        Vs = [i.real for i in Vs]
        V_l, V_g = min(Vs), max(Vs)
        return dPsat_dT*T*(V_g - V_l)

    def dH_dep_dT_sat_l(self, T, polish=False):
        r'''Method to calculate and return the temperature derivative of
        saturation liquid excess enthalpy.

        Parameters
        ----------
        T : float
            Temperature, [K]
        polish : bool, optional
            Whether to perform a rigorous calculation or to use a polynomial
            fit, [-]

        Returns
        -------
        dH_dep_dT_sat_l : float
            Liquid phase temperature derivative of excess enthalpy along the
            liquid-vapor saturation line, [J/mol/K]

        Notes
        -----
        '''
        sat_eos = self.to(T=T, P=self.Psat(T, polish=polish))
        dfg_T, dfl_T = sat_eos.dfugacity_dT_g, sat_eos.dfugacity_dT_l
        dfg_P, dfl_P = sat_eos.dfugacity_dP_g, sat_eos.dfugacity_dP_l
        dPsat_dT = (dfg_T - dfl_T)/(dfl_P - dfg_P)
        return dPsat_dT*sat_eos.dH_dep_dP_l + sat_eos.dH_dep_dT_l

    def dH_dep_dT_sat_g(self, T, polish=False):
        r'''Method to calculate and return the temperature derivative of
        saturation vapor excess enthalpy.

        Parameters
        ----------
        T : float
            Temperature, [K]
        polish : bool, optional
            Whether to perform a rigorous calculation or to use a polynomial
            fit, [-]

        Returns
        -------
        dH_dep_dT_sat_g : float
            Vapor phase temperature derivative of excess enthalpy along the
            liquid-vapor saturation line, [J/mol/K]

        Notes
        -----
        '''
        sat_eos = self.to(T=T, P=self.Psat(T, polish=polish))
        dfg_T, dfl_T = sat_eos.dfugacity_dT_g, sat_eos.dfugacity_dT_l
        dfg_P, dfl_P = sat_eos.dfugacity_dP_g, sat_eos.dfugacity_dP_l
        dPsat_dT = (dfg_T - dfl_T)/(dfl_P - dfg_P)
        return dPsat_dT*sat_eos.dH_dep_dP_g + sat_eos.dH_dep_dT_g

    def dS_dep_dT_sat_g(self, T, polish=False):
        r'''Method to calculate and return the temperature derivative of
        saturation vapor excess entropy.

        Parameters
        ----------
        T : float
            Temperature, [K]
        polish : bool, optional
            Whether to perform a rigorous calculation or to use a polynomial
            fit, [-]

        Returns
        -------
        dS_dep_dT_sat_g : float
            Vapor phase temperature derivative of excess entropy along the
            liquid-vapor saturation line, [J/mol/K^2]

        Notes
        -----
        '''
        sat_eos = self.to(T=T, P=self.Psat(T, polish=polish))
        dfg_T, dfl_T = sat_eos.dfugacity_dT_g, sat_eos.dfugacity_dT_l
        dfg_P, dfl_P = sat_eos.dfugacity_dP_g, sat_eos.dfugacity_dP_l
        dPsat_dT = (dfg_T - dfl_T)/(dfl_P - dfg_P)
        return dPsat_dT*sat_eos.dS_dep_dP_g + sat_eos.dS_dep_dT_g

    def dS_dep_dT_sat_l(self, T, polish=False):
        r'''Method to calculate and return the temperature derivative of
        saturation liquid excess entropy.

        Parameters
        ----------
        T : float
            Temperature, [K]
        polish : bool, optional
            Whether to perform a rigorous calculation or to use a polynomial
            fit, [-]

        Returns
        -------
        dS_dep_dT_sat_l : float
            Liquid phase temperature derivative of excess entropy along the
            liquid-vapor saturation line, [J/mol/K^2]

        Notes
        -----
        '''
        sat_eos = self.to(T=T, P=self.Psat(T, polish=polish))
        dfg_T, dfl_T = sat_eos.dfugacity_dT_g, sat_eos.dfugacity_dT_l
        dfg_P, dfl_P = sat_eos.dfugacity_dP_g, sat_eos.dfugacity_dP_l
        dPsat_dT = (dfg_T - dfl_T)/(dfl_P - dfg_P)
        return dPsat_dT*sat_eos.dS_dep_dP_l + sat_eos.dS_dep_dT_l


    def a_alpha_for_V(self, T, P, V):
        r'''Method to calculate which value of :math:`a \alpha` is required for
        a given `T`, `P` pair to match a specified `V`. This is a
        straightforward analytical equation.

        Parameters
        ----------
        T : float
            Temperature, [K]
        P : float
            Pressure, [Pa]
        V : float
            Molar volume, [m^3/mol]

        Returns
        -------
        a_alpha : float
            Value calculated to match specified volume for the current EOS,
            [J^2/mol^2/Pa]

        Notes
        -----
        The derivation of the solution is as follows:


        >>> from sympy import * # doctest:+SKIP
        >>> P, T, V, R, b, a, delta, epsilon = symbols('P, T, V, R, b, a, delta, epsilon') # doctest:+SKIP
        >>> a_alpha = symbols('a_alpha') # doctest:+SKIP
        >>> CUBIC = R*T/(V-b) - a_alpha/(V*V + delta*V + epsilon) # doctest:+SKIP
        >>> solve(Eq(CUBIC, P), a_alpha)# doctest:+SKIP
        [(-P*V**3 + P*V**2*b - P*V**2*delta + P*V*b*delta - P*V*epsilon + P*b*epsilon + R*T*V**2 + R*T*V*delta + R*T*epsilon)/(V - b)]
        '''
        b, delta, epsilon = self.b, self.delta, self.epsilon
        x0 = P*b
        x1 = R*T
        x2 = V*delta
        x3 = V*V
        x4 = x3*V
        return ((-P*x4 - P*V*epsilon - P*delta*x3 + epsilon*x0 + epsilon*x1
                 + x0*x2 + x0*x3 + x1*x2 + x1*x3)/(V - b))


    def a_alpha_for_Psat(self, T, Psat, a_alpha_guess=None):
        r'''Method to calculate which value of :math:`a \alpha` is required for
        a given `T`, `Psat` pair. This is a numerical solution, but not a very
        complicated one.

        Parameters
        ----------
        T : float
            Temperature, [K]
        Psat : float
            Vapor pressure specified, [Pa]
        a_alpha_guess : float
            Optionally, an initial guess for the solver [J^2/mol^2/Pa]

        Returns
        -------
        a_alpha : float
            Value calculated to match specified volume for the current EOS,
            [J^2/mol^2/Pa]

        Notes
        -----
        The implementation of this function is a direct calculation of
        departure gibbs energy, which is equal in both phases at saturation.

        Examples
        --------
        >>> eos = PR(Tc=507.6, Pc=3025000, omega=0.2975, T=299., P=1E6)
        >>> eos.a_alpha_for_Psat(T=400, Psat=5e5)
        3.1565798926
        '''
        P = Psat
        b, delta, epsilon = self.b, self.delta, self.epsilon
        RT = R*T
        RT_inv = 1.0/RT
        x0 = 1.0/sqrt(delta*delta - 4.0*epsilon)
        x1 = delta*x0
        x2 = 2.0*x0

        def fug(V, a_alpha):
            # Can simplify this to not use a function, avoid 1 log anywayS
            G_dep = (P*V - RT - RT*log(P*RT_inv*(V-b))
                      - x2*a_alpha*catanh(2.0*V*x0 + x1).real)
            return G_dep # No point going all the way to fugacity

        def err(a_alpha):
            # Needs some work right up to critical point
            Vs = self.volume_solutions(T, P, b, delta, epsilon, a_alpha)
            good_roots = [i.real for i in Vs if i.imag == 0.0 and i.real > 0.0]
            good_root_count = len(good_roots)
            if good_root_count == 1:
                raise ValueError("Guess did not have two roots")
            V_l, V_g = min(good_roots), max(good_roots)
#            print(V_l, V_g, a_alpha)
            return fug(V_l, a_alpha) - fug(V_g, a_alpha)

        if a_alpha_guess is None:
            try:
                a_alpha_guess = self.a_alpha
            except AttributeError:
                a_alpha_guess = 0.002

        try:
            return secant(err, a_alpha_guess, xtol=1e-13)
        except:
            return secant(err, self.to(T=T, P=Psat).a_alpha, xtol=1e-13)

    def to_TP(self, T, P):
        r'''Method to construct a new EOS object at the spcified `T` and `P`.
        In the event the `T` and `P` match the current object's `T` and `P`,
        it will be returned unchanged.

        Parameters
        ----------
        T : float
            Temperature, [K]
        P : float
            Pressure, [Pa]

        Returns
        -------
        obj : EOS
            Pure component EOS at specified `T` and `P`, [-]

        Notes
        -----
        Constructs the object with parameters `Tc`, `Pc`, `omega`, and
        `kwargs`.

        Examples
        --------

        >>> base = PR(Tc=507.6, Pc=3025000.0, omega=0.2975, T=500.0, P=1E6)
        >>> new = base.to_TP(T=1.0, P=2.0)
        >>> base.state_specs, new.state_specs
        ({'T': 500.0, 'P': 1000000.0}, {'T': 1.0, 'P': 2.0})
        '''
        if T != self.T or P != self.P:
            return self.__class__(T=T, P=P, Tc=self.Tc, Pc=self.Pc, omega=self.omega, **self.kwargs)
        else:
            return self

    def to_TV(self, T, V):
        r'''Method to construct a new EOS object at the spcified `T` and `V`.
        In the event the `T` and `V` match the current object's `T` and `V`,
        it will be returned unchanged.

        Parameters
        ----------
        T : float
            Temperature, [K]
        V : float
            Molar volume, [m^3/mol]

        Returns
        -------
        obj : EOS
            Pure component EOS at specified `T` and `V`, [-]

        Notes
        -----
        Constructs the object with parameters `Tc`, `Pc`, `omega`, and
        `kwargs`.

        Examples
        --------

        >>> base = PR(Tc=507.6, Pc=3025000.0, omega=0.2975, T=500.0, P=1E6)
        >>> new = base.to_TV(T=1000000.0, V=1.0)
        >>> base.state_specs, new.state_specs
        ({'T': 500.0, 'P': 1000000.0}, {'T': 1000000.0, 'V': 1.0})
        '''
        if T != self.T or V != self.V:
            # Only allow creation of new class if volume actually specified
            # Ignores the posibility that V is V_l or V_g
            return self.__class__(T=T, V=V, Tc=self.Tc, Pc=self.Pc, omega=self.omega, **self.kwargs)
        else:
            return self

    def to_PV(self, P, V):
        r'''Method to construct a new EOS object at the spcified `P` and `V`.
        In the event the `P` and `V` match the current object's `P` and `V`,
        it will be returned unchanged.

        Parameters
        ----------
        P : float
            Pressure, [Pa]
        V : float
            Molar volume, [m^3/mol]

        Returns
        -------
        obj : EOS
            Pure component EOS at specified `P` and `V`, [-]

        Notes
        -----
        Constructs the object with parameters `Tc`, `Pc`, `omega`, and
        `kwargs`.

        Examples
        --------

        >>> base = PR(Tc=507.6, Pc=3025000.0, omega=0.2975, T=500.0, P=1E6)
        >>> new = base.to_PV(P=1000.0, V=1.0)
        >>> base.state_specs, new.state_specs
        ({'T': 500.0, 'P': 1000000.0}, {'P': 1000.0, 'V': 1.0})
        '''
        if P != self.P or V != self.V:
            return self.__class__(V=V, P=P, Tc=self.Tc, Pc=self.Pc, omega=self.omega, **self.kwargs)
        else:
            return self

    def to(self, T=None, P=None, V=None):
        r'''Method to construct a new EOS object at two of `T`, `P` or `V`.
        In the event the specs match those of the current object, it will be
        returned unchanged.

        Parameters
        ----------
        T : float or None, optional
            Temperature, [K]
        P : float or None, optional
            Pressure, [Pa]
        V : float or None, optional
            Molar volume, [m^3/mol]

        Returns
        -------
        obj : EOS
            Pure component EOS at the two specified specs, [-]

        Notes
        -----
        Constructs the object with parameters `Tc`, `Pc`, `omega`, and
        `kwargs`.

        Examples
        --------

        >>> base = PR(Tc=507.6, Pc=3025000.0, omega=0.2975, T=500.0, P=1E6)
        >>> base.to(T=300.0, P=1e9).state_specs
        {'T': 300.0, 'P': 1000000000.0}
        >>> base.to(T=300.0, V=1.0).state_specs
        {'T': 300.0, 'V': 1.0}
        >>> base.to(P=1e5, V=1.0).state_specs
        {'P': 100000.0, 'V': 1.0}
        '''
        if T is not None and P is not None:
            return self.to_TP(T, P)
        elif T is not None and V is not None:
            return self.to_TV(T, V)
        elif P is not None and V is not None:
            return self.to_PV(P, V)
        else:
            # Error message
            return self.__class__(T=T, V=V, P=P, Tc=self.Tc, Pc=self.Pc, omega=self.omega, **self.kwargs)

    def T_min_at_V(self, V, Pmin=1e-15):
        '''Returns the minimum temperature for the EOS to have the
        volume as specified. Under this temperature, the pressure will go
        negative (and the EOS will not solve).
        '''
        return self.solve_T(P=Pmin, V=V)

    def T_max_at_V(self, V, Pmax=None):
        r'''Method to calculate the maximum temperature the EOS can create at a
        constant volume, if one exists; returns None otherwise.

        Parameters
        ----------
        V : float
            Constant molar volume, [m^3/mol]
        Pmax : float
            Maximum possible isochoric pressure, if already known [Pa]

        Returns
        -------
        T : float
            Maximum possible temperature, [K]

        Notes
        -----


        Examples
        --------
        >>> e = PR(P=1e5, V=0.0001437, Tc=512.5, Pc=8084000.0, omega=0.559)
        >>> e.T_max_at_V(e.V)
        431155.5
        '''
        if Pmax is None:
            Pmax = self.P_max_at_V(V)
            if Pmax is None:
                return None
        return self.solve_T(P=Pmax, V=V)

    def P_max_at_V(self, V):
        r'''Dummy method. The idea behind this method, which is implemented by some
        subclasses, is to calculate the maximum pressure the EOS can create at a
        constant volume, if one exists; returns None otherwise. This method,
        as a dummy method, always returns None.

        Parameters
        ----------
        V : float
            Constant molar volume, [m^3/mol]

        Returns
        -------
        P : float
            Maximum possible isochoric pressure, [Pa]
        '''
        return None

    @property
    def more_stable_phase(self):
        r'''Checks the Gibbs energy of each possible phase, and returns
        'l' if the liquid-like phase is more stable, and 'g' if the vapor-like
        phase is more stable.

        Examples
        --------
        >>> PR(Tc=507.6, Pc=3025000, omega=0.2975, T=299., P=1E6).more_stable_phase
        'l'
        '''
        try:
            if self.G_dep_l < self.G_dep_g:
                return 'l'
            else:
                return 'g'
        except:
            try:
                self.Z_g
                return 'g'
            except:
                return 'l'

    def discriminant(self, T=None, P=None):
        r'''Method to compute the discriminant of the cubic volume solution
        with the current EOS parameters, optionally at the same (assumed) `T`,
        and `P` or at different ones, if values are specified.

        Parameters
        ----------
        T : float, optional
            Temperature, [K]
        P : float, optional
            Pressure, [Pa]

        Returns
        -------
        discriminant : float
            Discriminant, [-]

        Notes
        -----
        This call is quite quick; only :math:`a \alpha` is needed and if `T` is
        the same as the current object than it has already been computed.

        The formula is as follows:

        .. math::
            \text{discriminant} = - \left(- \frac{27 P^{2} \epsilon \left(
            \frac{P b}{R T} + 1\right)}{R^{2} T^{2}} - \frac{27 P^{2} b
            \operatorname{a \alpha}{\left(T \right)}}{R^{3} T^{3}}\right)
            \left(- \frac{P^{2} \epsilon \left(\frac{P b}{R T} + 1\right)}
            {R^{2} T^{2}} - \frac{P^{2} b \operatorname{a \alpha}{\left(T
            \right)}}{R^{3} T^{3}}\right) + \left(- \frac{P^{2} \epsilon \left(
            \frac{P b}{R T} + 1\right)}{R^{2} T^{2}} - \frac{P^{2} b
            \operatorname{a \alpha}{\left(T \right)}}{R^{3} T^{3}}\right)
            \left(- \frac{18 P b}{R T} + \frac{18 P \delta}{R T} - 18\right)
            \left(\frac{P^{2} \epsilon}{R^{2} T^{2}} - \frac{P \delta \left(
            \frac{P b}{R T} + 1\right)}{R T} + \frac{P \operatorname{a \alpha}
            {\left(T \right)}}{R^{2} T^{2}}\right) - \left(- \frac{P^{2}
            \epsilon \left(\frac{P b}{R T} + 1\right)}{R^{2} T^{2}} - \frac{
            P^{2} b \operatorname{a \alpha}{\left(T \right)}}{R^{3} T^{3}}
            \right) \left(- \frac{4 P b}{R T} + \frac{4 P \delta}{R T}
            - 4\right) \left(- \frac{P b}{R T} + \frac{P \delta}{R T}
            - 1\right)^{2} + \left(- \frac{P b}{R T} + \frac{P \delta}{R T}
            - 1\right)^{2} \left(\frac{P^{2} \epsilon}{R^{2} T^{2}} - \frac{P
            \delta \left(\frac{P b}{R T} + 1\right)}{R T} + \frac{P
            \operatorname{a \alpha}{\left(T \right)}}{R^{2} T^{2}}\right)^{2}
            - \left(\frac{P^{2} \epsilon}{R^{2} T^{2}} - \frac{P \delta \left(
            \frac{P b}{R T} + 1\right)}{R T} + \frac{P \operatorname{a \alpha}{
            \left(T \right)}}{R^{2} T^{2}}\right)^{2} \left(\frac{4 P^{2}
            \epsilon}{R^{2} T^{2}} - \frac{4 P \delta \left(\frac{P b}{R T}
            + 1\right)}{R T} + \frac{4 P \operatorname{a \alpha}{\left(T
            \right)}}{R^{2} T^{2}}\right)

        The formula is derived as follows:

        >>> from sympy import *
        >>> P, T, R, b = symbols('P, T, R, b')
        >>> a_alpha = symbols(r'a\ \alpha', cls=Function)
        >>> delta, epsilon = symbols('delta, epsilon')
        >>> eta = b
        >>> B = b*P/(R*T)
        >>> deltas = delta*P/(R*T)
        >>> thetas = a_alpha(T)*P/(R*T)**2
        >>> epsilons = epsilon*(P/(R*T))**2
        >>> etas = eta*P/(R*T)
        >>> a = 1
        >>> b = (deltas - B - 1)
        >>> c = (thetas + epsilons - deltas*(B+1))
        >>> d = -(epsilons*(B+1) + thetas*etas)
        >>> disc = b*b*c*c - 4*a*c*c*c - 4*b*b*b*d - 27*a*a*d*d + 18*a*b*c*d

        Examples
        --------
        >>> base = PR(Tc=507.6, Pc=3025000.0, omega=0.2975, T=500.0, P=1E6)
        >>> base.discriminant()
        -0.001026390999
        >>> base.discriminant(T=400)
         0.0010458828
        >>> base.discriminant(T=400, P=1e9)
        12584660355.4
        '''
        if P is None:
            P = self.P
        if T is None:
            T = self.T
            a_alpha = self.a_alpha
        else:
            a_alpha = self.a_alpha_and_derivatives(T, full=False)
        RT = R*self.T
        RT6 = RT*RT
        RT6 *= RT6*RT6
        x0 = P*P
        x1 = P*self.b + RT
        x2 = a_alpha*self.b + self.epsilon*x1
        x3 = P*self.epsilon
        x4 = self.delta*x1
        x5 = -P*self.delta + x1
        x6 = a_alpha + x3 - x4
        x2_2 = x2*x2
        x5_2 = x5*x5
        x6_2 = x6*x6
        x7 = (-a_alpha - x3 + x4)
        return x0*(18.0*P*x2*x5*x6 + 4.0*P*x7*x7*x7
                   - 27.0*x0*x2_2 - 4.0*x2*x5_2*x5 + x5_2*x6_2)/RT6


    def _discriminant_at_T_mp(self, P):
        # Hopefully numerical difficulties can eventually be figured out to as to
        # not need mpmath
        import mpmath as mp
        mp.mp.dps = 70
        P, T, b, a_alpha, delta, epsilon, R_mp = [mp.mpf(i) for i in [P, self.T, self.b, self.a_alpha, self.delta, self.epsilon, R]]
        RT = R_mp*T
        RT6 = RT**6
        x0 = P*P
        x1 = P*b + RT
        x2 = a_alpha*b + epsilon*x1
        x3 = P*epsilon
        x4 = delta*x1
        x5 = -P*delta + x1
        x6 = a_alpha + x3 - x4
        x2_2 = x2*x2
        x5_2 = x5*x5
        x6_2 = x6*x6
        disc = (x0*(18.0*P*x2*x5*x6 + 4.0*P*(-a_alpha - x3 + x4)**3
                   - 27.0*x0*x2_2 - 4.0*x2*x5_2*x5 + x5_2*x6_2)/RT6)
        return disc

    def P_discriminant_zero_l(self):
        r'''Method to calculate the pressure which zero the discriminant
        function of the general cubic eos, and is likely to sit on a boundary
        between not having a liquid-like volume; and having a liquid-like volume.

        Returns
        -------
        P_discriminant_zero_l : float
            Pressure which make the discriminants zero at the right condition,
            [Pa]

        Notes
        -----

        Examples
        --------
        >>> eos = PRTranslatedConsistent(Tc=507.6, Pc=3025000, omega=0.2975, T=299., P=1E6)
        >>> P_trans = eos.P_discriminant_zero_l()
        >>> P_trans
        478346.37289

        In this case, the discriminant transition shows the change in roots:

        >>> eos.to(T=eos.T, P=P_trans*.99999999).mpmath_volumes_float
        ((0.00013117994140177062+0j), (0.002479717165903531+0j), (0.002480236178570793+0j))
        >>> eos.to(T=eos.T, P=P_trans*1.0000001).mpmath_volumes_float
        ((0.0001311799413872173+0j), (0.002479976386402769-8.206310112063695e-07j), (0.002479976386402769+8.206310112063695e-07j))
        '''
        return self._P_discriminant_zero(low=True)

    def P_discriminant_zero_g(self):
        r'''Method to calculate the pressure which zero the discriminant
        function of the general cubic eos, and is likely to sit on a boundary
        between not having a vapor-like volume; and having a vapor-like volume.

        Returns
        -------
        P_discriminant_zero_g : float
            Pressure which make the discriminants zero at the right condition,
            [Pa]

        Notes
        -----

        Examples
        --------
        >>> eos = PRTranslatedConsistent(Tc=507.6, Pc=3025000, omega=0.2975, T=299., P=1E6)
        >>> P_trans = eos.P_discriminant_zero_g()
        >>> P_trans
        149960391.7

        In this case, the discriminant transition does not reveal a transition
        to two roots being available, only negative roots becoming negative
        and imaginary.

        >>> eos.to(T=eos.T, P=P_trans*.99999999).mpmath_volumes_float
        ((-0.0001037013146195082-1.5043987866732543e-08j), (-0.0001037013146195082+1.5043987866732543e-08j), (0.00011799201928619508+0j))
        >>> eos.to(T=eos.T, P=P_trans*1.0000001).mpmath_volumes_float
        ((-0.00010374888853182635+0j), (-0.00010365374200380354+0j), (0.00011799201875924273+0j))
        '''
        return self._P_discriminant_zero(low=False)

    def P_discriminant_zeros(self):
        r'''Method to calculate the pressures which zero the discriminant
        function of the general cubic eos, at the current temperature.

        Returns
        -------
        P_discriminant_zeros : list[float]
            Pressures which make the discriminants zero, [Pa]

        Notes
        -----

        Examples
        --------
        >>> eos = PRTranslatedConsistent(Tc=507.6, Pc=3025000, omega=0.2975, T=299., P=1E6)
        >>> eos.P_discriminant_zeros()
        [478346.3, 149960391.7]
        '''
        return GCEOS.P_discriminant_zeros_analytical(self.T, self.b, self.delta, self.epsilon, self.a_alpha, valid=True)

    @staticmethod
    def P_discriminant_zeros_analytical(T, b, delta, epsilon, a_alpha, valid=False):
        r'''Method to calculate the pressures which zero the discriminant
        function of the general cubic eos. This is a quartic function
        solved analytically.


        Parameters
        ----------
        T : float
            Temperature, [K]
        b : float
            Coefficient calculated by EOS-specific method, [m^3/mol]
        delta : float
            Coefficient calculated by EOS-specific method, [m^3/mol]
        epsilon : float
            Coefficient calculated by EOS-specific method, [m^6/mol^2]
        a_alpha : float
            Coefficient calculated by EOS-specific method, [J^2/mol^2/Pa]
        valid : bool
            Whether to filter the calculated pressures so that they are all
            real, and positive only, [-]

        Returns
        -------
        P_discriminant_zeros : float
            Pressures which make the discriminants zero, [Pa]

        Notes
        -----
        Calculated analytically. Derived as follows.

        >>> from sympy import *
        >>> P, T, V, R, b, a, delta, epsilon = symbols('P, T, V, R, b, a, delta, epsilon')
        >>> eta = b
        >>> B = b*P/(R*T)
        >>> deltas = delta*P/(R*T)
        >>> thetas = a*P/(R*T)**2
        >>> epsilons = epsilon*(P/(R*T))**2
        >>> etas = eta*P/(R*T)
        >>> a_coeff = 1
        >>> b_coeff = (deltas - B - 1)
        >>> c = (thetas + epsilons - deltas*(B+1))
        >>> d = -(epsilons*(B+1) + thetas*etas)
        >>> disc = b_coeff*b_coeff*c*c - 4*a_coeff*c*c*c - 4*b_coeff*b_coeff*b_coeff*d - 27*a_coeff*a_coeff*d*d + 18*a_coeff*b_coeff*c*d
        >>> base = -(expand(disc/P**2*R**3*T**3))
        >>> sln = collect(base, P)
        '''
        # Can also have one at g
#        T, a_alpha = self.T, self.a_alpha
        a = a_alpha
#        b, epsilon, delta = self.b, self.epsilon, self.delta

        T_inv = 1.0/T
        # TODO cse
        x0 = 4.0*a
        x1 = b*x0
        x2 = a+a
        x3 = delta*x2
        x4 = R*T
        x5 = 4.0*epsilon
        x6 = delta*delta
        x7 = a*a
        x8 = T_inv*R_inv
        x9 = 8.0*epsilon
        x10 = b*x9
        x11 = 4.0*delta
        x12 = delta*x6
        x13 = 2.0*x6
        x14 = b*x13
        x15 = a*x8
        x16 = epsilon*x15
        x20 = x8*x8
        x17 = x20*x8
        x18 = b*delta
        x19 = 6.0*x15
        x21 = x20*x7
        x22 = 10.0*b
        x23 = b*b
        x24 = 6.0*x23
        x25 = x0*x8
        x26 = x6*x6
        x27 = epsilon*epsilon
        x28 = 8.0*x27
        x29 = 24.0*epsilon
        x30 = b*x12
        x31 = epsilon*x13
        x32 = epsilon*x8
        x33 = 12.0*epsilon
        x34 = b*x23
        x35 = x2*x8
        x36 = 8.0*x21
        x37 = x15*x6
        x38 = delta*x23
        x39 = b*x28
        x40 = x34*x9
        x41 = epsilon*x12
        x42 = x23*x23

        e = x1 + x3 + x4*x5 - x4*x6 - x7*x8
        d = (4.0*x7*a*x17 - 10.0*delta*x21 + 2.0*(epsilon*x11 + x10 - x12
             - x14 + x15*x24 + x18*x19 - x21*x22 + x25*x6) - 20.0*x16)
        c = x8*(-x1*x32 + x12*x35 + x15*(12.0*x34 + 18.0*x38) + x18*(x29 + x36)
                + x21*(x33 - x6) + x22*x37 + x23*(x29 + x36) - x24*x6 - x26
                + x28 - x3*x32 - 6.0*x30 + x31)
        b_coeff = (2.0*x20*(-b*x26 + delta*(x10*x15 + x25*x34) + epsilon*x14
                            + x23*(x15*x9 - 3.0*x12 + x37) - x13*x34 - x15*x30
                            -x16*x6 + x27*(x19 + x11) + x33*x38 + x35*x42
                            + x39 + x40 - x41))
        a_coeff = x17*(-2.0*b*x41 + delta*(x39 + x40)
                       + x27*(4.0*epsilon - x6)
                       - 2.0*x12*x34 + x23*(x28 + x31 - x26)
                       + x42*(x5 - x6))

#        e = (2*a*delta + 4*a*b -R*T*delta**2 - a**2/(R*T) + 4*R*T*epsilon)
#        d = (-4*b*delta**2 + 16*b*epsilon - 2*delta**3 + 8*delta*epsilon + 12*a*b**2/(R*T) + 12*a*b*delta/(R*T) + 8*a*delta**2/(R*T) - 20*a*epsilon/(R*T) - 20*a**2*b/(R**2*T**2) - 10*a**2*delta/(R**2*T**2) + 4*a**3/(R**3*T**3))
#        c = (-6*b**2*delta**2/(R*T) + 24*b**2*epsilon/(R*T) - 6*b*delta**3/(R*T) + 24*b*delta*epsilon/(R*T) - delta**4/(R*T) + 2*delta**2*epsilon/(R*T) + 8*epsilon**2/(R*T) + 12*a*b**3/(R**2*T**2) + 18*a*b**2*delta/(R**2*T**2) + 10*a*b*delta**2/(R**2*T**2) - 4*a*b*epsilon/(R**2*T**2) + 2*a*delta**3/(R**2*T**2) - 2*a*delta*epsilon/(R**2*T**2) + 8*a**2*b**2/(R**3*T**3) + 8*a**2*b*delta/(R**3*T**3) - a**2*delta**2/(R**3*T**3) + 12*a**2*epsilon/(R**3*T**3))
#        b_coeff = (-4*b**3*delta**2/(R**2*T**2) + 16*b**3*epsilon/(R**2*T**2) - 6*b**2*delta**3/(R**2*T**2) + 24*b**2*delta*epsilon/(R**2*T**2) - 2*b*delta**4/(R**2*T**2) + 4*b*delta**2*epsilon/(R**2*T**2) + 16*b*epsilon**2/(R**2*T**2) - 2*delta**3*epsilon/(R**2*T**2) + 8*delta*epsilon**2/(R**2*T**2) + 4*a*b**4/(R**3*T**3) + 8*a*b**3*delta/(R**3*T**3) + 2*a*b**2*delta**2/(R**3*T**3) + 16*a*b**2*epsilon/(R**3*T**3) - 2*a*b*delta**3/(R**3*T**3) + 16*a*b*delta*epsilon/(R**3*T**3) - 2*a*delta**2*epsilon/(R**3*T**3) + 12*a*epsilon**2/(R**3*T**3))
#        a_coeff = (-b**4*delta**2/(R**3*T**3) + 4*b**4*epsilon/(R**3*T**3) - 2*b**3*delta**3/(R**3*T**3) + 8*b**3*delta*epsilon/(R**3*T**3) - b**2*delta**4/(R**3*T**3) + 2*b**2*delta**2*epsilon/(R**3*T**3) + 8*b**2*epsilon**2/(R**3*T**3) - 2*b*delta**3*epsilon/(R**3*T**3) + 8*b*delta*epsilon**2/(R**3*T**3) - delta**2*epsilon**2/(R**3*T**3) + 4*epsilon**3/(R**3*T**3))
        roots = roots_quartic(a_coeff, b_coeff, c, d, e)
#        roots = np.roots([a_coeff, b_coeff, c, d, e]).tolist()
        if valid:
            # TODO - only include ones when switching phases from l/g to either g/l
            # Do not know how to handle
            roots = [r.real for r in roots if (r.real >= 0.0)]
            roots.sort()
        return roots


    def _P_discriminant_zero(self, low):
        # Can also have one at g
        T, a_alpha = self.T, self.a_alpha
        b, epsilon, delta = self.b, self.epsilon, self.delta
        global niter
        niter = 0
        RT = R*T
        x13 = RT**-6.0
        x14 = b*epsilon
        x15 = -b*delta + epsilon
        x18 = b - delta
        def discriminant_fun(P):
            if P < 0:
                raise ValueError("Will not converge")
            global niter
            niter += 1
            x0 = P*P
            x1 = P*epsilon
            x2 = P*b + RT
            x3 = a_alpha - delta*x2 + x1
            x3_x3 = x3*x3
            x4 = x3*x3_x3
            x5 = a_alpha*b + epsilon*x2
            x6 = 27.0*x5*x5
            x7 = -P*delta + x2
            x9 = x7*x7
            x8 = x7*x9
            x11 = x3*x5*x7
            x12 = -18.0*P*x11 + 4.0*(P*x4 +x5*x8) + x0*x6 - x3_x3*x9
            x16 = P*x15
            x17 = 9.0*x3
            x19 = x18*x5
            # 26 mult so far
            err = -x0*x12*x13
            fprime = (-2.0*P*x13*(P*(-P*x17*x19 + P*x6 - b*x1*x17*x7
                                     + 27.0*x0*x14*x5 + 6.0*x3_x3*x16 - x3_x3*x18*x7
                                     - 9.0*x11 + 2.0*x14*x8 - x15*x3*x9 - 9.0*x16*x5*x7 + 6.0*x19*x9 + 2.0*x4) + x12))

            if niter > 3 and (.40 < (err/(P*fprime)) < 0.55):
                raise ValueError("Not going to work")
                # a = (err/fprime)/P
                # print('low probably kill point')
            return err, fprime

        # New answer: Above critical T only high P result
        # Ps = logspace(log10(1), log10(1e10), 40000)
        # errs = []
        # for P in Ps:
        #     erri = self.discriminant(P=P)
        #     if erri < 0:
        #         erri = -log10(abs(erri))
        #     else:
        #         erri = log10(erri)
        #     errs.append(erri)
        # import matplotlib.pyplot as plt
        # plt.semilogx(Ps, errs, 'x')
        # # plt.ylim((-1e-3, 1e-3))
        # plt.show()

        # Checked once
        # def damping_func(p0, step, damping):
        #     if p0 + step < 0.0:
        #         return 0.9*p0
        #     # while p0 + step < 1e3:
        #     # if p0 + step < 1e3:
        #     #     step = 0.5*step
        #     return p0 + step
        #low=1,damping_func=damping_func
        # 5e7

        try:
            Tc = self.Tc
        except:
            Tc = self.pseudo_Tc


        guesses = [1e5, 1e6, 1e7, 1e8, 1e9, .5, 1e-4, 1e-8, 1e-12, 1e-16, 1e-20]
        if not low:
            guesses = [1e9, 1e10, 1e10, 5e10, 2e10, 5e9, 5e8, 1e8]
        if self.N == 1 and low:
            try:
                try:
                    Tc, Pc, omega = self.Tc, self.Pc, self.omega
                except:
                    Tc, Pc, omega = self.Tcs[0], self.Pcs[0], self.omegas[0]
                guesses.append(Pc*.99999999)
                assert T/Tc > .3
                P_wilson = Wilson_K_value(self.T, self.P, Tc, Pc, omega)*self.P
                guesses.insert(0, P_wilson*3)
            except:
                pass

        if low:
            coeffs = self._P_zero_l_cheb_coeffs
            coeffs_low, coeffs_high = self.P_zero_l_cheb_limits
        else:
            coeffs = self._P_zero_g_cheb_coeffs
            coeffs_low, coeffs_high = self.P_zero_g_cheb_limits


        if coeffs is not None:
            try:
                a = self.a
            except:
                a = self.pseudo_a
            alpha = self.a_alpha/a

            try:
                Pc = self.Pc
            except:
                Pc = self.pseudo_Pc

            Tr = self.T/Tc
            alpha_Tr = alpha/(Tr)
            x = alpha_Tr - 1.0
            if coeffs_low < x <  coeffs_high:
                constant = 0.5*(-coeffs_low - coeffs_high)
                factor = 2.0/(coeffs_high - coeffs_low)

                y = chebval(factor*(x + constant), coeffs)
                P_trans = y*Tr*Pc

                guesses.insert(0, P_trans)


        global_iter = 0
        for P in guesses:
            try:
                global_iter += niter
                niter = 0
                # try:
                #     P_disc = newton(discriminant_fun, P, fprime=True, xtol=1e-16, low=1, maxiter=200, bisection=False, damping=1)
                # except:
#                high = None
#                if self.N == 1:
#                    try:
#                        high = self.Pc
#                    except:
#                        high = self.Pcs[0]
#                    high *= (1+1e-11)
                if not low and T < Tc:
                    low_bound = 1e8
                else:
                    if Tr > .3:
                        low_bound = 1.0
                    else:
                        low_bound = None
                P_disc = newton(discriminant_fun, P, fprime=True, xtol=4e-12, low=low_bound,
                                maxiter=80, bisection=False, damping=1)
                assert P_disc > 0 and not P_disc == 1
                if not low:
                    assert P_disc > low_bound
                break
            except:
                pass

        if not low:
            assert P_disc > low_bound


        global_iter += niter
        # for i in range(1000):
        #     a = 1

        if 0:
            try:
                P_disc = bisect(self._discriminant_at_T_mp, P_disc*(1-1e-8), P_disc*(1+1e-8), xtol=1e-18)
            except:
                try:
                    P_disc = bisect(self._discriminant_at_T_mp, P_disc*(1-1e-5), P_disc*(1+1e-5), xtol=1e-18)
                except:
                    try:
                        P_disc = bisect(self._discriminant_at_T_mp, P_disc*(1-1e-2), P_disc*(1+1e-2))
                    except:
                        pass

#        if not low:
#            P_disc_base = None
#            try:
#                if T < Tc:
#                    P_disc_base = self._P_discriminant_zero(True)
#            except:
#                pass
#            if P_disc_base is not None:
#                # pass
#               if isclose(P_disc_base, P_disc, rel_tol=1e-4):
#                   raise ValueError("Converged to wrong solution")


        return float(P_disc)


        # Can take a while to converge
        P_disc = secant(lambda P: self.discriminant(P=P), self.P, xtol=1e-7, low=1e-12, maxiter=200, bisection=True)
        if P_disc <= 0.0:
            P_disc = secant(lambda P: self.discriminant(P=P), self.P*100, xtol=1e-7, maxiter=200)
#            P_max = self.P*1000
#            P_disc = brenth(lambda P: self.discriminant(P=P), self.P*1e-3, P_max, rtol=1e-7, maxiter=200)
        return P_disc

    def _plot_T_discriminant_zero(self):
         Ts = logspace(log10(1), log10(1e4), 10000)
         errs = []
         for T in Ts:
             erri = self.discriminant(T=T)
#             if erri < 0:
#                 erri = -log10(abs(erri))
#             else:
#                 erri = log10(erri)
             errs.append(erri)
         import matplotlib.pyplot as plt
         plt.semilogx(Ts, errs, 'x')
#         plt.ylim((-1e-3, 1e-3))
         plt.show()

    def T_discriminant_zero_l(self, T_guess=None):
        r'''Method to calculate the temperature which zeros the discriminant
        function of the general cubic eos, and is likely to sit on a boundary
        between not having a liquid-like volume; and having a liquid-like volume.

        Parameters
        ----------
        T_guess : float, optional
            Temperature guess, [K]

        Returns
        -------
        T_discriminant_zero_l : float
            Temperature which make the discriminants zero at the right condition,
            [K]

        Notes
        -----
        Significant numerical issues remain in improving this method.

        Examples
        --------
        >>> eos = PRTranslatedConsistent(Tc=507.6, Pc=3025000, omega=0.2975, T=299., P=1E6)
        >>> T_trans = eos.T_discriminant_zero_l()
        >>> T_trans
        644.3023307

        In this case, the discriminant transition does not reveal a transition
        to two roots being available, only to there being a double (imaginary)
        root.

        >>> eos.to(P=eos.P, T=T_trans).mpmath_volumes_float
        ((9.309597822372529e-05-0.00015876248805149625j), (9.309597822372529e-05+0.00015876248805149625j), (0.005064847204219234+0j))
        '''
        # Can also have one at g
        global niter
        niter = 0
        guesses = [100, 150, 200, 250, 300, 350, 400, 450]
        if T_guess is not None:
            guesses.append(T_guess)
        if self.N == 1:
            pass

        global_iter = 0
        for T in guesses:
            try:
                global_iter += niter
                niter = 0
                T_disc = secant(lambda T: self.discriminant(T=T), T, xtol=1e-10, low=1, maxiter=60, bisection=False, damping=1)
                assert T_disc > 0 and not T_disc == 1
                break
            except:
                pass
        global_iter += niter
        return T_disc

    def T_discriminant_zero_g(self, T_guess=None):
        r'''Method to calculate the temperature which zeros the discriminant
        function of the general cubic eos, and is likely to sit on a boundary
        between not having a vapor-like volume; and having a vapor-like volume.

        Parameters
        ----------
        T_guess : float, optional
            Temperature guess, [K]

        Returns
        -------
        T_discriminant_zero_g : float
            Temperature which make the discriminants zero at the right condition,
            [K]

        Notes
        -----
        Significant numerical issues remain in improving this method.

        Examples
        --------
        >>> eos = PRTranslatedConsistent(Tc=507.6, Pc=3025000, omega=0.2975, T=299., P=1E6)
        >>> T_trans = eos.T_discriminant_zero_g()
        >>> T_trans
        644.3023307

        In this case, the discriminant transition does not reveal a transition
        to two roots being available, only to there being a double (imaginary)
        root.

        >>> eos.to(P=eos.P, T=T_trans).mpmath_volumes_float
        ((9.309597822372529e-05-0.00015876248805149625j), (9.309597822372529e-05+0.00015876248805149625j), (0.005064847204219234+0j))
        '''
        global niter
        niter = 0
        guesses = [700, 600, 500, 400, 300, 200]
        if T_guess is not None:
            guesses.append(T_guess)
        if self.N == 1:
            pass

        global_iter = 0
        for T in guesses:
            try:
                global_iter += niter
                niter = 0
                T_disc = secant(lambda T: self.discriminant(T=T), T, xtol=1e-10, low=1, maxiter=60, bisection=False, damping=1)
                assert T_disc > 0 and not T_disc == 1
                break
            except:
                pass
        global_iter += niter
        return T_disc

    def P_PIP_transition(self, T, low_P_limit=0.0):
        r'''Method to calculate the pressure which makes the phase
        identification parameter exactly 1. There are three regions for this
        calculation:

            * subcritical - PIP = 1 for the gas-like phase at P = 0
            * initially supercritical - PIP = 1 on a curve starting at the
              critical point, increasing for a while, decreasing for a while,
              and then curving sharply back to a zero pressure.
            * later supercritical - PIP = 1 for the liquid-like phase at P = 0

        Parameters
        ----------
        T : float
            Temperature for the calculation, [K]
        low_P_limit : float
            What value to return for the subcritical and later region, [Pa]

        Returns
        -------
        P : float
            Pressure which makes the PIP = 1, [Pa]

        Notes
        -----
        The transition between the region where this function returns values
        and the high temperature region that doesn't is the Joule-Thomson
        inversion point at a pressure of zero and can be directly solved for.

        Examples
        --------
        >>> eos = PRTranslatedConsistent(Tc=507.6, Pc=3025000, omega=0.2975, T=299., P=1E6)
        >>> eos.P_PIP_transition(100)
        0.0
        >>> low_T = eos.to(T=100.0, P=eos.P_PIP_transition(100, low_P_limit=1e-5))
        >>> low_T.PIP_l, low_T.PIP_g
        (45.778088191, 0.9999999997903)
        >>> initial_super = eos.to(T=600.0, P=eos.P_PIP_transition(600))
        >>> initial_super.P, initial_super.PIP_g
        (6456282.17132, 0.999999999999)
        >>> high_T = eos.to(T=900.0, P=eos.P_PIP_transition(900, low_P_limit=1e-5))
        >>> high_T.P, high_T.PIP_g
        (12536704.763, 0.9999999999)
        '''
        subcritical = T < self.Tc
        if subcritical:
            return low_P_limit
        else:
            def to_solve(P):
                e = self.to(T=T, P=P)
                # TODO: as all a_alpha is the same for all conditions, should be
                # able to derive a direct expression for this from the EOS which
                # only uses a volume solution
                # TODO: should be able to get the derivative of PIP w.r.t. pressure
                if hasattr(e, 'V_l'):
                    return e.PIP_l-1.0
                else:
                    return e.PIP_g-1.0
        try:
            # Near the critical point these equations turn extremely nasty!
            # bisection is the most reliable solver
            if subcritical:
                Psat = self.Psat(T)
                low, high = 10.0*Psat, Psat
            else:
                low, high = 1e-3, 1e11
            P = bisect(to_solve, low, high)
            return P
        except:
            err_low = to_solve(low_P_limit)
            if abs(err_low) < 1e-9:
                # Well above the critical point all solutions except the
                # zero-pressure limit have PIP values above 1
                # This corresponds to the JT inversion temperature at a
                # pressure of zero.
                return low_P_limit
            raise ValueError("Could not converge")



    def _V_g_extrapolated(self):
        P_pseudo_mc = sum([self.Pcs[i]*self.zs[i] for i in self.cmps])
        T_pseudo_mc = sum([(self.Tcs[i]*self.Tcs[j])**0.5*self.zs[j]*self.zs[i]
                           for i in self.cmps for j in self.cmps])
        V_pseudo_mc = (self.Zc*R*T_pseudo_mc)/P_pseudo_mc
        rho_pseudo_mc = 1.0/V_pseudo_mc

        P_disc = self.P_discriminant_zero_l()

        try:
            P_low = max(P_disc - 10.0, 1e-3)
            eos_low = self.to_TP_zs(T=self.T, P=P_low, zs=self.zs)
            rho_low = 1.0/eos_low.V_g
        except:
            P_low = max(P_disc + 10.0, 1e-3)
            eos_low = self.to_TP_zs(T=self.T, P=P_low, zs=self.zs)
            rho_low = 1.0/eos_low.V_g

        rho0 = (rho_low + 1.4*rho_pseudo_mc)*0.5

        dP_drho = eos_low.dP_drho_g
        rho1 = P_low*((rho_low - 1.4*rho_pseudo_mc) + P_low/dP_drho)

        rho2 = -P_low*P_low*((rho_low - 1.4*rho_pseudo_mc)*0.5 + P_low/dP_drho)
        rho_ans = rho0 + rho1/eos_low.P + rho2/(eos_low.P*eos_low.P)
        return 1.0/rho_ans

    @property
    def fugacity_l(self):
        r'''Fugacity for the liquid phase, [Pa].

        .. math::
            \text{fugacity} = P\exp\left(\frac{G_{dep}}{RT}\right)
        '''
        arg = self.G_dep_l*R_inv/self.T
        try:
            return self.P*exp(arg)
        except:
            return self.P*1e308

    @property
    def fugacity_g(self):
        r'''Fugacity for the gas phase, [Pa].

        .. math::
            \text{fugacity} = P\exp\left(\frac{G_{dep}}{RT}\right)
        '''
        arg = self.G_dep_g*R_inv/self.T
        try:
            return self.P*exp(arg)
        except:
            return self.P*1e308

    @property
    def phi_l(self):
        r'''Fugacity coefficient for the liquid phase, [Pa].

        .. math::
            \phi = \frac{\text{fugacity}}{P}
        '''
        arg = self.G_dep_l*R_inv/self.T
        try:
            return exp(arg)
        except:
            return 1e308

    @property
    def phi_g(self):
        r'''Fugacity coefficient for the gas phase, [Pa].

        .. math::
            \phi = \frac{\text{fugacity}}{P}
        '''
        arg = self.G_dep_g*R_inv/self.T
        try:
            return exp(arg)
        except:
            return 1e308

    @property
    def Cp_minus_Cv_l(self):
        r'''Cp - Cv for the liquid phase, [J/mol/K].

        .. math::
            C_p - C_v = -T\left(\frac{\partial P}{\partial T}\right)_V^2/
            \left(\frac{\partial P}{\partial V}\right)_T
        '''
        return -self.T*self.dP_dT_l*self.dP_dT_l*self.dV_dP_l

    @property
    def Cp_minus_Cv_g(self):
        r'''Cp - Cv for the gas phase, [J/mol/K].

        .. math::
            C_p - C_v = -T\left(\frac{\partial P}{\partial T}\right)_V^2/
            \left(\frac{\partial P}{\partial V}\right)_T
        '''
        return -self.T*self.dP_dT_g*self.dP_dT_g*self.dV_dP_g

    @property
    def beta_l(self):
        r'''Isobaric (constant-pressure) expansion coefficient for the liquid
        phase, [1/K].

        .. math::
            \beta = \frac{1}{V}\frac{\partial V}{\partial T}
        '''
        return self.dV_dT_l/self.V_l

    @property
    def beta_g(self):
        r'''Isobaric (constant-pressure) expansion coefficient for the gas
        phase, [1/K].

        .. math::
            \beta = \frac{1}{V}\frac{\partial V}{\partial T}
        '''
        return self.dV_dT_g/self.V_g

    @property
    def kappa_l(self):
        r'''Isothermal (constant-temperature) expansion coefficient for the liquid
        phase, [1/Pa].

        .. math::
            \kappa = \frac{-1}{V}\frac{\partial V}{\partial P}
        '''
        return -self.dV_dP_l/self.V_l

    @property
    def kappa_g(self):
        r'''Isothermal (constant-temperature) expansion coefficient for the gas
        phase, [1/Pa].

        .. math::
            \kappa = \frac{-1}{V}\frac{\partial V}{\partial P}
        '''
        return -self.dV_dP_g/self.V_g

    @property
    def V_dep_l(self):
        r'''Departure molar volume from ideal gas behavior for the liquid phase,
        [m^3/mol].

        .. math::
            V_{dep} = V - \frac{RT}{P}
        '''
        return self.V_l - self.T*R/self.P

    @property
    def V_dep_g(self):
        r'''Departure molar volume from ideal gas behavior for the gas phase,
        [m^3/mol].

        .. math::
            V_{dep} = V - \frac{RT}{P}
        '''
        return self.V_g - self.T*R/self.P

    @property
    def U_dep_l(self):
        r'''Departure molar internal energy from ideal gas behavior for the
        liquid phase, [J/mol].

        .. math::
            U_{dep} = H_{dep} - P V_{dep}
        '''
        return self.H_dep_l - self.P*(self.V_l - self.T*R/self.P)

    @property
    def U_dep_g(self):
        r'''Departure molar internal energy from ideal gas behavior for the
        gas phase, [J/mol].

        .. math::
            U_{dep} = H_{dep} - P V_{dep}
        '''
        return self.H_dep_g - self.P*(self.V_g - self.T*R/self.P)

    @property
    def A_dep_l(self):
        r'''Departure molar Helmholtz energy from ideal gas behavior for the
        liquid phase, [J/mol].

        .. math::
            A_{dep} = U_{dep} - T S_{dep}
        '''
        return self.H_dep_l - self.P*(self.V_l - self.T*R/self.P) - self.T*self.S_dep_l

    @property
    def A_dep_g(self):
        r'''Departure molar Helmholtz energy from ideal gas behavior for the
        gas phase, [J/mol].

        .. math::
            A_{dep} = U_{dep} - T S_{dep}
        '''
        return self.H_dep_g - self.P*(self.V_g - self.T*R/self.P) - self.T*self.S_dep_g

    @property
    def d2T_dPdV_l(self):
        r'''Second partial derivative of temperature with respect to
        pressure (constant volume) and then volume (constant pressure)
        for the liquid phase, [K*mol/(Pa*m^3)].

        .. math::
           \left(\frac{\partial^2 T}{\partial P\partial V}\right) =
            - \left[\left(\frac{\partial^2 P}{\partial T \partial V}\right)
            \left(\frac{\partial P}{\partial T}\right)_V
            - \left(\frac{\partial P}{\partial V}\right)_T
            \left(\frac{\partial^2 P}{\partial T^2}\right)_V
            \right]\left(\frac{\partial P}{\partial T}\right)_V^{-3}

        '''
        inverse_dP_dT2 = self.dT_dP_l*self.dT_dP_l
        inverse_dP_dT3 = inverse_dP_dT2*self.dT_dP_l
        d2T_dPdV = -(self.d2P_dTdV_l*self.dP_dT_l - self.dP_dV_l*self.d2P_dT2_l)*inverse_dP_dT3
        return d2T_dPdV

    @property
    def d2T_dPdV_g(self):
        r'''Second partial derivative of temperature with respect to
        pressure (constant volume) and then volume (constant pressure)
        for the gas phase, [K*mol/(Pa*m^3)].

        .. math::
           \left(\frac{\partial^2 T}{\partial P\partial V}\right) =
            - \left[\left(\frac{\partial^2 P}{\partial T \partial V}\right)
            \left(\frac{\partial P}{\partial T}\right)_V
            - \left(\frac{\partial P}{\partial V}\right)_T
            \left(\frac{\partial^2 P}{\partial T^2}\right)_V
            \right]\left(\frac{\partial P}{\partial T}\right)_V^{-3}

        '''
        inverse_dP_dT2 = self.dT_dP_g*self.dT_dP_g
        inverse_dP_dT3 = inverse_dP_dT2*self.dT_dP_g
        d2T_dPdV = -(self.d2P_dTdV_g*self.dP_dT_g - self.dP_dV_g*self.d2P_dT2_g)*inverse_dP_dT3
        return d2T_dPdV

    @property
    def d2V_dPdT_l(self):
        r'''Second partial derivative of volume with respect to
        pressure (constant temperature) and then presssure (constant temperature)
        for the liquid phase, [m^3/(K*Pa*mol)].

        .. math::
            \left(\frac{\partial^2 V}{\partial T\partial P}\right) =
            - \left[\left(\frac{\partial^2 P}{\partial T \partial V}\right)
            \left(\frac{\partial P}{\partial V}\right)_T
            - \left(\frac{\partial P}{\partial T}\right)_V
            \left(\frac{\partial^2 P}{\partial V^2}\right)_T
            \right]\left(\frac{\partial P}{\partial V}\right)_T^{-3}
        '''
        dV_dP = self.dV_dP_l
        return -(self.d2P_dTdV_l*self.dP_dV_l - self.dP_dT_l*self.d2P_dV2_l)*dV_dP*dV_dP*dV_dP

    @property
    def d2V_dPdT_g(self):
        r'''Second partial derivative of volume with respect to
        pressure (constant temperature) and then presssure (constant temperature)
        for the gas phase, [m^3/(K*Pa*mol)].

        .. math::
            \left(\frac{\partial^2 V}{\partial T\partial P}\right) =
            - \left[\left(\frac{\partial^2 P}{\partial T \partial V}\right)
            \left(\frac{\partial P}{\partial V}\right)_T
            - \left(\frac{\partial P}{\partial T}\right)_V
            \left(\frac{\partial^2 P}{\partial V^2}\right)_T
            \right]\left(\frac{\partial P}{\partial V}\right)_T^{-3}
        '''
        dV_dP = self.dV_dP_g
        return -(self.d2P_dTdV_g*self.dP_dV_g - self.dP_dT_g*self.d2P_dV2_g)*dV_dP*dV_dP*dV_dP

    @property
    def d2T_dP2_l(self):
        r'''Second partial derivative of temperature with respect to
        pressure (constant temperature) for the liquid phase, [K/Pa^2].

        .. math::
            \left(\frac{\partial^2 T}{\partial P^2}\right)_V = -\left(\frac{
            \partial^2 P}{\partial T^2}\right)_V \left(\frac{\partial P}{
            \partial T}\right)^{-3}_V

        '''
        dT_dP = self.dT_dP_l
        return -self.d2P_dT2_l*dT_dP*dT_dP*dT_dP # unused

    @property
    def d2T_dP2_g(self):
        r'''Second partial derivative of temperature with respect to
        pressure (constant volume) for the gas phase, [K/Pa^2].

        .. math::
            \left(\frac{\partial^2 T}{\partial P^2}\right)_V = -\left(\frac{
            \partial^2 P}{\partial T^2}\right)_V \left(\frac{\partial P}{
            \partial T}\right)^{-3}_V

        '''
        dT_dP = self.dT_dP_g
        return -self.d2P_dT2_g*dT_dP*dT_dP*dT_dP # unused

    @property
    def d2V_dP2_l(self):
        r'''Second partial derivative of volume with respect to
        pressure (constant temperature) for the liquid phase, [m^3/(Pa^2*mol)].

        .. math::
            \left(\frac{\partial^2 V}{\partial P^2}\right)_T = -\left(\frac{
            \partial^2 P}{\partial V^2}\right)_T \left(\frac{\partial P}{
            \partial V}\right)^{-3}_T

        '''
        dV_dP = self.dV_dP_l
        return -self.d2P_dV2_l*dV_dP*dV_dP*dV_dP

    @property
    def d2V_dP2_g(self):
        r'''Second partial derivative of volume with respect to
        pressure (constant temperature) for the gas phase, [m^3/(Pa^2*mol)].

        .. math::
            \left(\frac{\partial^2 V}{\partial P^2}\right)_T = -\left(\frac{
            \partial^2 P}{\partial V^2}\right)_T \left(\frac{\partial P}{
            \partial V}\right)^{-3}_T

        '''
        dV_dP = self.dV_dP_g
        return -self.d2P_dV2_g*dV_dP*dV_dP*dV_dP

    @property
    def d2T_dV2_l(self):
        r'''Second partial derivative of temperature with respect to
        volume (constant pressure) for the liquid phase, [K*mol^2/m^6].

        .. math::
            \left(\frac{\partial^2 T}{\partial V^2}\right)_P = -\left[
            \left(\frac{\partial^2 P}{\partial V^2}\right)_T
            \left(\frac{\partial P}{\partial T}\right)_V
            - \left(\frac{\partial P}{\partial V}\right)_T
            \left(\frac{\partial^2 P}{\partial T \partial V}\right) \right]
            \left(\frac{\partial P}{\partial T}\right)^{-2}_V
            + \left[\left(\frac{\partial^2 P}{\partial T\partial V}\right)
            \left(\frac{\partial P}{\partial T}\right)_V
            - \left(\frac{\partial P}{\partial V}\right)_T
            \left(\frac{\partial^2 P}{\partial T^2}\right)_V\right]
            \left(\frac{\partial P}{\partial T}\right)_V^{-3}
            \left(\frac{\partial P}{\partial V}\right)_T
        '''
        dT_dP = self.dT_dP_l
        dT_dP2 = dT_dP*dT_dP

        d2T_dV2 = dT_dP2*(-(self.d2P_dV2_l*self.dP_dT_l - self.dP_dV_l*self.d2P_dTdV_l)
                   +(self.d2P_dTdV_l*self.dP_dT_l - self.dP_dV_l*self.d2P_dT2_l)*dT_dP*self.dP_dV_l)
        return d2T_dV2

    @property
    def d2T_dV2_g(self):
        r'''Second partial derivative of temperature with respect to
        volume (constant pressure) for the gas phase, [K*mol^2/m^6].

        .. math::
            \left(\frac{\partial^2 T}{\partial V^2}\right)_P = -\left[
            \left(\frac{\partial^2 P}{\partial V^2}\right)_T
            \left(\frac{\partial P}{\partial T}\right)_V
            - \left(\frac{\partial P}{\partial V}\right)_T
            \left(\frac{\partial^2 P}{\partial T \partial V}\right) \right]
            \left(\frac{\partial P}{\partial T}\right)^{-2}_V
            + \left[\left(\frac{\partial^2 P}{\partial T\partial V}\right)
            \left(\frac{\partial P}{\partial T}\right)_V
            - \left(\frac{\partial P}{\partial V}\right)_T
            \left(\frac{\partial^2 P}{\partial T^2}\right)_V\right]
            \left(\frac{\partial P}{\partial T}\right)_V^{-3}
            \left(\frac{\partial P}{\partial V}\right)_T
        '''
        dT_dP = self.dT_dP_g
        dT_dP2 = dT_dP*dT_dP

        d2T_dV2 = dT_dP2*(-(self.d2P_dV2_g*self.dP_dT_g - self.dP_dV_g*self.d2P_dTdV_g)
                   +(self.d2P_dTdV_g*self.dP_dT_g - self.dP_dV_g*self.d2P_dT2_g)*dT_dP*self.dP_dV_g)
        return d2T_dV2


    @property
    def d2V_dT2_l(self):
        r'''Second partial derivative of volume with respect to
        temperature (constant pressure) for the liquid phase, [m^3/(mol*K^2)].

        .. math::
            \left(\frac{\partial^2 V}{\partial T^2}\right)_P = -\left[
            \left(\frac{\partial^2 P}{\partial T^2}\right)_V
            \left(\frac{\partial P}{\partial V}\right)_T
            - \left(\frac{\partial P}{\partial T}\right)_V
            \left(\frac{\partial^2 P}{\partial T \partial V}\right) \right]
            \left(\frac{\partial P}{\partial V}\right)^{-2}_T
            + \left[\left(\frac{\partial^2 P}{\partial T\partial V}\right)
            \left(\frac{\partial P}{\partial V}\right)_T
            - \left(\frac{\partial P}{\partial T}\right)_V
            \left(\frac{\partial^2 P}{\partial V^2}\right)_T\right]
            \left(\frac{\partial P}{\partial V}\right)_T^{-3}
            \left(\frac{\partial P}{\partial T}\right)_V

        '''
        dV_dP = self.dV_dP_l
        dP_dV = self.dP_dV_l
        d2P_dTdV = self.d2P_dTdV_l
        dP_dT = self.dP_dT_l
        d2V_dT2 = dV_dP*dV_dP*(-(self.d2P_dT2_l*dP_dV - dP_dT*d2P_dTdV) # unused
                   +(d2P_dTdV*dP_dV - dP_dT*self.d2P_dV2_l)*dV_dP*dP_dT)
        return d2V_dT2


    @property
    def d2V_dT2_g(self):
        r'''Second partial derivative of volume with respect to
        temperature (constant pressure) for the gas phase, [m^3/(mol*K^2)].

        .. math::
            \left(\frac{\partial^2 V}{\partial T^2}\right)_P = -\left[
            \left(\frac{\partial^2 P}{\partial T^2}\right)_V
            \left(\frac{\partial P}{\partial V}\right)_T
            - \left(\frac{\partial P}{\partial T}\right)_V
            \left(\frac{\partial^2 P}{\partial T \partial V}\right) \right]
            \left(\frac{\partial P}{\partial V}\right)^{-2}_T
            + \left[\left(\frac{\partial^2 P}{\partial T\partial V}\right)
            \left(\frac{\partial P}{\partial V}\right)_T
            - \left(\frac{\partial P}{\partial T}\right)_V
            \left(\frac{\partial^2 P}{\partial V^2}\right)_T\right]
            \left(\frac{\partial P}{\partial V}\right)_T^{-3}
            \left(\frac{\partial P}{\partial T}\right)_V

        '''
        dV_dP = self.dV_dP_g
        dP_dV = self.dP_dV_g
        d2P_dTdV = self.d2P_dTdV_g
        dP_dT = self.dP_dT_g
        d2V_dT2 = dV_dP*dV_dP*(-(self.d2P_dT2_g*dP_dV - dP_dT*d2P_dTdV) # unused
                   +(d2P_dTdV*dP_dV - dP_dT*self.d2P_dV2_g)*dV_dP*dP_dT)
        return d2V_dT2

    @property
    def Vc(self):
        r'''Critical volume, [m^3/mol].

        .. math::
            V_c = \frac{Z_c R T_c}{P_c}

        '''
        return self.Zc*R*self.Tc/self.Pc

    @property
    def rho_l(self):
        r'''Liquid molar density, [mol/m^3].

        .. math::
            \rho_l = \frac{1}{V_l}

        '''
        return 1.0/self.V_l

    @property
    def rho_g(self):
        r'''Gas molar density, [mol/m^3].

        .. math::
            \rho_g = \frac{1}{V_g}

        '''
        return 1.0/self.V_g


    @property
    def dZ_dT_l(self):
        r'''Derivative of compressibility factor with respect to temperature
        for the liquid phase, [1/K].

        .. math::
            \frac{\partial Z}{\partial T} = \frac{P}{RT}\left(
            \frac{\partial V}{\partial T} - \frac{V}{T}
            \right)

        '''
        T_inv = 1.0/self.T
        return self.P*R_inv*T_inv*(self.dV_dT_l - self.V_l*T_inv)

    @property
    def dZ_dT_g(self):
        r'''Derivative of compressibility factor with respect to temperature
        for the gas phase, [1/K].

        .. math::
            \frac{\partial Z}{\partial T} = \frac{P}{RT}\left(
            \frac{\partial V}{\partial T} - \frac{V}{T}
            \right)

        '''
        T_inv = 1.0/self.T
        return self.P*R_inv*T_inv*(self.dV_dT_g - self.V_g*T_inv)

    @property
    def dZ_dP_l(self):
        r'''Derivative of compressibility factor with respect to pressure
        for the liquid phase, [1/Pa].

        .. math::
            \frac{\partial Z}{\partial P} = \frac{1}{RT}\left(
            V - \frac{\partial V}{\partial P}
            \right)

        '''
        return (self.V_l + self.P*self.dV_dP_l)/(self.T*R)

    @property
    def dZ_dP_g(self):
        r'''Derivative of compressibility factor with respect to pressure
        for the gas phase, [1/Pa].

        .. math::
            \frac{\partial Z}{\partial P} = \frac{1}{RT}\left(
            V - \frac{\partial V}{\partial P}
            \right)

        '''
        return (self.V_g + self.P*self.dV_dP_g)/(self.T*R)

    d2V_dTdP_l = d2V_dPdT_l
    d2V_dTdP_g = d2V_dPdT_g
    d2T_dVdP_l = d2T_dPdV_l
    d2T_dVdP_g = d2T_dPdV_g

    @property
    def d2P_dVdT_l(self):
        '''Alias of :obj:`GCEOS.d2P_dTdV_l`'''
        return self.d2P_dTdV_l

    @property
    def d2P_dVdT_g(self):
        '''Alias of :obj:`GCEOS.d2P_dTdV_g`'''
        return self.d2P_dTdV_g

    @property
    def dP_drho_l(self):
        r'''Derivative of pressure with respect to molar density for the liquid
        phase, [Pa/(mol/m^3)].

        .. math::
            \frac{\partial P}{\partial \rho} = -V^2 \frac{\partial P}{\partial V}
        '''
        return -self.V_l*self.V_l*self.dP_dV_l

    @property
    def dP_drho_g(self):
        r'''Derivative of pressure with respect to molar density for the gas
        phase, [Pa/(mol/m^3)].

        .. math::
            \frac{\partial P}{\partial \rho} = -V^2 \frac{\partial P}{\partial V}
        '''
        return -self.V_g*self.V_g*self.dP_dV_g

    @property
    def drho_dP_l(self):
        r'''Derivative of molar density with respect to pressure for the liquid
        phase, [(mol/m^3)/Pa].

        .. math::
            \frac{\partial \rho}{\partial P} = \frac{-1}{V^2} \frac{\partial V}{\partial P}
        '''
        return -self.dV_dP_l/(self.V_l*self.V_l)

    @property
    def drho_dP_g(self):
        r'''Derivative of molar density with respect to pressure for the gas
        phase, [(mol/m^3)/Pa].

        .. math::
            \frac{\partial \rho}{\partial P} = \frac{-1}{V^2} \frac{\partial V}{\partial P}
        '''
        return -self.dV_dP_g/(self.V_g*self.V_g)

    @property
    def d2P_drho2_l(self):
        r'''Second derivative of pressure with respect to molar density for the
        liquid phase, [Pa/(mol/m^3)^2].

        .. math::
            \frac{\partial^2 P}{\partial \rho^2} = -V^2\left(
            -V^2\frac{\partial^2 P}{\partial V^2} - 2V \frac{\partial P}{\partial V}
            \right)
        '''
        return -self.V_l**2*(-self.V_l**2*self.d2P_dV2_l - 2*self.V_l*self.dP_dV_l)

    @property
    def d2P_drho2_g(self):
        r'''Second derivative of pressure with respect to molar density for the
        gas phase, [Pa/(mol/m^3)^2].

        .. math::
            \frac{\partial^2 P}{\partial \rho^2} = -V^2\left(
            -V^2\frac{\partial^2 P}{\partial V^2} - 2V \frac{\partial P}{\partial V}
            \right)
        '''
        return -self.V_g**2*(-self.V_g**2*self.d2P_dV2_g - 2*self.V_g*self.dP_dV_g)

    @property
    def d2rho_dP2_l(self):
        r'''Second derivative of molar density with respect to pressure for the
        liquid phase, [(mol/m^3)/Pa^2].

        .. math::
            \frac{\partial^2 \rho}{\partial P^2} =
            -\frac{\partial^2 V}{\partial P^2}\frac{1}{V^2}
            + 2 \left(\frac{\partial V}{\partial P}\right)^2\frac{1}{V^3}
        '''
        return -self.d2V_dP2_l/self.V_l**2 + 2*self.dV_dP_l**2/self.V_l**3

    @property
    def d2rho_dP2_g(self):
        r'''Second derivative of molar density with respect to pressure for the
        gas phase, [(mol/m^3)/Pa^2].

        .. math::
            \frac{\partial^2 \rho}{\partial P^2} =
            -\frac{\partial^2 V}{\partial P^2}\frac{1}{V^2}
            + 2 \left(\frac{\partial V}{\partial P}\right)^2\frac{1}{V^3}
        '''
        return -self.d2V_dP2_g/self.V_g**2 + 2*self.dV_dP_g**2/self.V_g**3


    @property
    def dT_drho_l(self):
        r'''Derivative of temperature with respect to molar density for the
        liquid phase, [K/(mol/m^3)].

        .. math::
            \frac{\partial T}{\partial \rho} = V^2 \frac{\partial T}{\partial V}
        '''
        return -self.V_l*self.V_l*self.dT_dV_l

    @property
    def dT_drho_g(self):
        r'''Derivative of temperature with respect to molar density for the
        gas phase, [K/(mol/m^3)].

        .. math::
            \frac{\partial T}{\partial \rho} = V^2 \frac{\partial T}{\partial V}
        '''
        return -self.V_g*self.V_g*self.dT_dV_g

    @property
    def d2T_drho2_l(self):
        r'''Second derivative of temperature with respect to molar density for
        the liquid phase, [K/(mol/m^3)^2].

        .. math::
            \frac{\partial^2 T}{\partial \rho^2} =
            -V^2(-V^2 \frac{\partial^2 T}{\partial V^2} -2V \frac{\partial T}{\partial V}  )
        '''
        return -self.V_l**2*(-self.V_l**2*self.d2T_dV2_l - 2*self.V_l*self.dT_dV_l)

    @property
    def d2T_drho2_g(self):
        r'''Second derivative of temperature with respect to molar density for
        the gas phase, [K/(mol/m^3)^2].

        .. math::
            \frac{\partial^2 T}{\partial \rho^2} =
            -V^2(-V^2 \frac{\partial^2 T}{\partial V^2} -2V \frac{\partial T}{\partial V}  )
        '''
        return -self.V_g**2*(-self.V_g**2*self.d2T_dV2_g - 2*self.V_g*self.dT_dV_g)


    @property
    def drho_dT_l(self):
        r'''Derivative of molar density with respect to temperature for the
        liquid phase, [(mol/m^3)/K].

        .. math::
            \frac{\partial \rho}{\partial T} = - \frac{1}{V^2}
            \frac{\partial V}{\partial T}
        '''
        return -self.dV_dT_l/(self.V_l*self.V_l)

    @property
    def drho_dT_g(self):
        r'''Derivative of molar density with respect to temperature for the
        gas phase, [(mol/m^3)/K].

        .. math::
            \frac{\partial \rho}{\partial T} = - \frac{1}{V^2}
            \frac{\partial V}{\partial T}
        '''
        return -self.dV_dT_g/(self.V_g*self.V_g)

    @property
    def d2rho_dT2_l(self):
        r'''Second derivative of molar density with respect to temperature for
        the liquid phase, [(mol/m^3)/K^2].

        .. math::
            \frac{\partial^2 \rho}{\partial T^2} =
            -\frac{\partial^2 V}{\partial T^2}\frac{1}{V^2}
            + 2 \left(\frac{\partial V}{\partial T}\right)^2\frac{1}{V^3}
        '''
        return -self.d2V_dT2_l/self.V_l**2 + 2*self.dV_dT_l**2/self.V_l**3

    @property
    def d2rho_dT2_g(self):
        r'''Second derivative of molar density with respect to temperature for
        the gas phase, [(mol/m^3)/K^2].

        .. math::
            \frac{\partial^2 \rho}{\partial T^2} =
            -\frac{\partial^2 V}{\partial T^2}\frac{1}{V^2}
            + 2 \left(\frac{\partial V}{\partial T}\right)^2\frac{1}{V^3}
        '''
        return -self.d2V_dT2_g/self.V_g**2 + 2*self.dV_dT_g**2/self.V_g**3

    @property
    def d2P_dTdrho_l(self):
        r'''Derivative of pressure with respect to molar density, and
        temperature for the liquid phase, [Pa/(K*mol/m^3)].

        .. math::
            \frac{\partial^2 P}{\partial \rho\partial T}
            = -V^2 \frac{\partial^2 P}{\partial T \partial V}
        '''
        return -(self.V_l*self.V_l)*self.d2P_dTdV_l

    @property
    def d2P_dTdrho_g(self):
        r'''Derivative of pressure with respect to molar density, and
        temperature for the gas phase, [Pa/(K*mol/m^3)].

        .. math::
            \frac{\partial^2 P}{\partial \rho\partial T}
            = -V^2 \frac{\partial^2 P}{\partial T \partial V}
        '''
        return -(self.V_g*self.V_g)*self.d2P_dTdV_g

    @property
    def d2T_dPdrho_l(self):
        r'''Derivative of temperature with respect to molar density, and
        pressure for the liquid phase, [K/(Pa*mol/m^3)].

        .. math::
            \frac{\partial^2 T}{\partial \rho\partial P}
            = -V^2 \frac{\partial^2 T}{\partial P \partial V}
        '''
        return -(self.V_l*self.V_l)*self.d2T_dPdV_l

    @property
    def d2T_dPdrho_g(self):
        r'''Derivative of temperature with respect to molar density, and
        pressure for the gas phase, [K/(Pa*mol/m^3)].

        .. math::
            \frac{\partial^2 T}{\partial \rho\partial P}
            = -V^2 \frac{\partial^2 T}{\partial P \partial V}
        '''
        return -(self.V_g*self.V_g)*self.d2T_dPdV_g

    @property
    def d2rho_dPdT_l(self):
        r'''Second derivative of molar density with respect to pressure
        and temperature for the liquid phase, [(mol/m^3)/(K*Pa)].

        .. math::
            \frac{\partial^2 \rho}{\partial T \partial P} =
            -\frac{\partial^2 V}{\partial T \partial P}\frac{1}{V^2}
            + 2 \left(\frac{\partial V}{\partial T}\right)
            \left(\frac{\partial V}{\partial P}\right)
            \frac{1}{V^3}
        '''
        return -self.d2V_dPdT_l/self.V_l**2 + 2*self.dV_dT_l*self.dV_dP_l/self.V_l**3

    @property
    def d2rho_dPdT_g(self):
        r'''Second derivative of molar density with respect to pressure
        and temperature for the gas phase, [(mol/m^3)/(K*Pa)].

        .. math::
            \frac{\partial^2 \rho}{\partial T \partial P} =
            -\frac{\partial^2 V}{\partial T \partial P}\frac{1}{V^2}
            + 2 \left(\frac{\partial V}{\partial T}\right)
            \left(\frac{\partial V}{\partial P}\right)
            \frac{1}{V^3}
        '''
        return -self.d2V_dPdT_g/self.V_g**2 + 2*self.dV_dT_g*self.dV_dP_g/self.V_g**3

    @property
    def dH_dep_dT_l(self):
        r'''Derivative of departure enthalpy with respect to
        temperature for the liquid phase, [(J/mol)/K].

        .. math::
            \frac{\partial H_{dep, l}}{\partial T} = P \frac{d}{d T} V{\left (T
            \right )} - R + \frac{2 T}{\sqrt{\delta^{2} - 4 \epsilon}}
                \operatorname{atanh}{\left (\frac{\delta + 2 V{\left (T \right
                )}}{\sqrt{\delta^{2} - 4 \epsilon}} \right )} \frac{d^{2}}{d
                T^{2}}  \operatorname{a \alpha}{\left (T \right )} + \frac{4
                \left(T \frac{d}{d T} \operatorname{a \alpha}{\left (T \right
                )} - \operatorname{a \alpha}{\left (T \right )}\right) \frac{d}
                {d T} V{\left (T \right )}}{\left(\delta^{2} - 4 \epsilon
                \right) \left(- \frac{\left(\delta + 2 V{\left (T \right )}
                \right)^{2}}{\delta^{2} - 4 \epsilon} + 1\right)}
        '''
        x0 = self.V_l
        x1 = self.dV_dT_l
        x2 = self.a_alpha
        x3 = self.delta*self.delta - 4.0*self.epsilon
        if x3 == 0.0:
            x3 = 1e-100

        x4 = x3**-0.5
        x5 = self.delta + x0 + x0
        x6 = 1.0/x3
        return (self.P*x1 - R + 2.0*self.T*x4*catanh(x4*x5).real*self.d2a_alpha_dT2
                - 4.0*x1*x6*(self.T*self.da_alpha_dT - x2)/(x5*x5*x6 - 1.0))

    @property
    def dH_dep_dT_g(self):
        r'''Derivative of departure enthalpy with respect to
        temperature for the gas phase, [(J/mol)/K].

        .. math::
            \frac{\partial H_{dep, g}}{\partial T} = P \frac{d}{d T} V{\left (T
            \right )} - R + \frac{2 T}{\sqrt{\delta^{2} - 4 \epsilon}}
                \operatorname{atanh}{\left (\frac{\delta + 2 V{\left (T \right
                )}}{\sqrt{\delta^{2} - 4 \epsilon}} \right )} \frac{d^{2}}{d
                T^{2}}  \operatorname{a \alpha}{\left (T \right )} + \frac{4
                \left(T \frac{d}{d T} \operatorname{a \alpha}{\left (T \right
                )} - \operatorname{a \alpha}{\left (T \right )}\right) \frac{d}
                {d T} V{\left (T \right )}}{\left(\delta^{2} - 4 \epsilon
                \right) \left(- \frac{\left(\delta + 2 V{\left (T \right )}
                \right)^{2}}{\delta^{2} - 4 \epsilon} + 1\right)}
        '''
        x0 = self.V_g
        x1 = self.dV_dT_g
        if x0 > 1e50:
            if isinf(self.dV_dT_g) or self.H_dep_g == 0.0:
                return 0.0
        x2 = self.a_alpha
        x3 = self.delta*self.delta - 4.0*self.epsilon
        if x3 == 0.0:
            x3 = 1e-100
        x4 = x3**-0.5
        x5 = self.delta + x0 + x0
        x6 = 1.0/x3
        return (self.P*x1 - R + 2.0*self.T*x4*catanh(x4*x5).real*self.d2a_alpha_dT2
                - 4.0*x1*x6*(self.T*self.da_alpha_dT - x2)/(x5*x5*x6 - 1.0))

    @property
    def dH_dep_dT_l_V(self):
        r'''Derivative of departure enthalpy with respect to
        temperature at constant volume for the liquid phase, [(J/mol)/K].

        .. math::
            \left(\frac{\partial H_{dep, l}}{\partial T}\right)_{V} =
            - R + \frac{2 T
            \operatorname{atanh}{\left(\frac{2 V_l + \delta}{\sqrt{\delta^{2}
            - 4 \epsilon}} \right)} \frac{d^{2}}{d T^{2}} \operatorname{
            a_{\alpha}}{\left(T \right)}}{\sqrt{\delta^{2} - 4 \epsilon}}
            + V_l \frac{\partial}{\partial T} P{\left(T,V \right)}
        '''
        T = self.T
        delta, epsilon = self.delta, self.epsilon
        V = self.V_l
        dP_dT = self.dP_dT_l
        try:
            x0 = (delta*delta - 4.0*epsilon)**-0.5
        except ZeroDivisionError:
            x0 = 1e100
        return -R + 2.0*T*x0*catanh(x0*(V + V + delta)).real*self.d2a_alpha_dT2 + V*dP_dT

    @property
    def dH_dep_dT_g_V(self):
        r'''Derivative of departure enthalpy with respect to
        temperature at constant volume for the gas phase, [(J/mol)/K].

        .. math::
            \left(\frac{\partial H_{dep, g}}{\partial T}\right)_{V} =
            - R + \frac{2 T
            \operatorname{atanh}{\left(\frac{2 V_g + \delta}{\sqrt{\delta^{2}
            - 4 \epsilon}} \right)} \frac{d^{2}}{d T^{2}} \operatorname{
                a_{\alpha}}{\left(T \right)}}{\sqrt{\delta^{2} - 4 \epsilon}}
                + V_g \frac{\partial}{\partial T} P{\left(T,V \right)}
        '''

        T = self.T
        delta, epsilon = self.delta, self.epsilon
        V = self.V_g
        dP_dT = self.dP_dT_g
        try:
            x0 = (delta*delta - 4.0*epsilon)**-0.5
        except ZeroDivisionError:
            x0 = 1e100
        return -R + 2.0*T*x0*catanh(x0*(V + V + delta)).real*self.d2a_alpha_dT2 + V*dP_dT

    @property
    def dH_dep_dP_l(self):
        r'''Derivative of departure enthalpy with respect to
        pressure for the liquid phase, [(J/mol)/Pa].

        .. math::
            \frac{\partial H_{dep, l}}{\partial P} = P \frac{d}{d P} V{\left (P
            \right )} + V{\left (P \right )} + \frac{4 \left(T \frac{d}{d T}
            \operatorname{a \alpha}{\left (T \right )} - \operatorname{a
            \alpha}{\left (T \right )}\right) \frac{d}{d P} V{\left (P \right
            )}}{\left(\delta^{2} - 4 \epsilon\right) \left(- \frac{\left(\delta
            + 2 V{\left (P \right )}\right)^{2}}{\delta^{2} - 4 \epsilon}
            + 1\right)}
        '''
        delta = self.delta
        x0 = self.V_l
        x2 = delta*delta - 4.0*self.epsilon
        x4 = (delta + x0 + x0)
        return (x0 + self.dV_dP_l*(self.P - 4.0*(self.T*self.da_alpha_dT
                - self.a_alpha)/(x4*x4 - x2)))

    @property
    def dH_dep_dP_g(self):
        r'''Derivative of departure enthalpy with respect to
        pressure for the gas phase, [(J/mol)/Pa].

        .. math::
            \frac{\partial H_{dep, g}}{\partial P} = P \frac{d}{d P} V{\left (P
            \right )} + V{\left (P \right )} + \frac{4 \left(T \frac{d}{d T}
            \operatorname{a \alpha}{\left (T \right )} - \operatorname{a
            \alpha}{\left (T \right )}\right) \frac{d}{d P} V{\left (P \right
            )}}{\left(\delta^{2} - 4 \epsilon\right) \left(- \frac{\left(\delta
            + 2 V{\left (P \right )}\right)^{2}}{\delta^{2} - 4 \epsilon}
            + 1\right)}
        '''
        delta = self.delta
        x0 = self.V_g
        x2 = delta*delta - 4.0*self.epsilon
        x4 = (delta + x0 + x0)
#        if isinf(self.dV_dP_g):
            # This does not appear to be correct
#            return 0.0
        return (x0 + self.dV_dP_g*(self.P - 4.0*(self.T*self.da_alpha_dT
                - self.a_alpha)/(x4*x4 - x2)))

    @property
    def dH_dep_dP_l_V(self):
        r'''Derivative of departure enthalpy with respect to
        pressure at constant volume for the gas phase, [(J/mol)/Pa].

        .. math::
            \left(\frac{\partial H_{dep, g}}{\partial P}\right)_{V} =
            - R \left(\frac{\partial T}{\partial P}\right)_V + V + \frac{2 \left(T
            \left(\frac{\partial \left(\frac{\partial a \alpha}{\partial T}
            \right)_P}{\partial P}\right)_{V}
            + \left(\frac{\partial a \alpha}{\partial T}\right)_P
            \left(\frac{\partial T}{\partial P}\right)_V - \left(\frac{
            \partial a \alpha}{\partial P}\right)_{V} \right)
            \operatorname{atanh}{\left(\frac{2 V + \delta}
            {\sqrt{\delta^{2} - 4 \epsilon}} \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}}
        '''

        T, V, delta, epsilon = self.T, self.V_l, self.delta, self.epsilon
        da_alpha_dT, d2a_alpha_dT2 = self.da_alpha_dT, self.d2a_alpha_dT2
        dT_dP = self.dT_dP_l

        d2a_alpha_dTdP_V = d2a_alpha_dT2*dT_dP
        da_alpha_dP_V = da_alpha_dT*dT_dP
        try:
            x0 = (delta*delta - 4.0*epsilon)**-0.5
        except ZeroDivisionError:
            x0 = 1e100

        return (-R*dT_dP + V + 2.0*x0*(
                T*d2a_alpha_dTdP_V + dT_dP*da_alpha_dT - da_alpha_dP_V)
                *catanh(x0*(V + V + delta)).real)

    @property
    def dH_dep_dP_g_V(self):
        r'''Derivative of departure enthalpy with respect to
        pressure at constant volume for the liquid phase, [(J/mol)/Pa].

        .. math::
            \left(\frac{\partial H_{dep, g}}{\partial P}\right)_{V} =
            - R \left(\frac{\partial T}{\partial P}\right)_V + V + \frac{2 \left(T
            \left(\frac{\partial \left(\frac{\partial a \alpha}{\partial T}
            \right)_P}{\partial P}\right)_{V}
            + \left(\frac{\partial a \alpha}{\partial T}\right)_P
            \left(\frac{\partial T}{\partial P}\right)_V - \left(\frac{
            \partial a \alpha}{\partial P}\right)_{V} \right)
            \operatorname{atanh}{\left(\frac{2 V + \delta}
            {\sqrt{\delta^{2} - 4 \epsilon}} \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}}
        '''
        T, V, delta, epsilon = self.T, self.V_g, self.delta, self.epsilon
        da_alpha_dT, d2a_alpha_dT2 = self.da_alpha_dT, self.d2a_alpha_dT2
        dT_dP = self.dT_dP_g

        d2a_alpha_dTdP_V = d2a_alpha_dT2*dT_dP
        da_alpha_dP_V = da_alpha_dT*dT_dP
        try:
            x0 = (delta*delta - 4.0*epsilon)**-0.5
        except ZeroDivisionError:
            x0 = 1e100

        return (-R*dT_dP + V + 2.0*x0*(
                T*d2a_alpha_dTdP_V + dT_dP*da_alpha_dT - da_alpha_dP_V)
                *catanh(x0*(V + V + delta)).real)

    @property
    def dH_dep_dV_g_T(self):
        r'''Derivative of departure enthalpy with respect to
        volume at constant temperature for the gas phase, [J/m^3].

        .. math::
            \left(\frac{\partial H_{dep, g}}{\partial V}\right)_{T} =
            \left(\frac{\partial H_{dep, g}}{\partial P}\right)_{T} \cdot
            \left(\frac{\partial P}{\partial V}\right)_{T}
        '''
        return self.dH_dep_dP_g*self.dP_dV_g

    @property
    def dH_dep_dV_l_T(self):
        r'''Derivative of departure enthalpy with respect to
        volume at constant temperature for the gas phase, [J/m^3].

        .. math::
            \left(\frac{\partial H_{dep, l}}{\partial V}\right)_{T} =
            \left(\frac{\partial H_{dep, l}}{\partial P}\right)_{T} \cdot
            \left(\frac{\partial P}{\partial V}\right)_{T}
        '''
        return self.dH_dep_dP_l*self.dP_dV_l

    @property
    def dH_dep_dV_g_P(self):
        r'''Derivative of departure enthalpy with respect to
        volume at constant pressure for the gas phase, [J/m^3].

        .. math::
            \left(\frac{\partial H_{dep, g}}{\partial V}\right)_{P} =
            \left(\frac{\partial H_{dep, g}}{\partial T}\right)_{P} \cdot
            \left(\frac{\partial T}{\partial V}\right)_{P}
        '''
        return self.dH_dep_dT_g*self.dT_dV_g

    @property
    def dH_dep_dV_l_P(self):
        r'''Derivative of departure enthalpy with respect to
        volume at constant pressure for the liquid phase, [J/m^3].

        .. math::
            \left(\frac{\partial H_{dep, l}}{\partial V}\right)_{P} =
            \left(\frac{\partial H_{dep, l}}{\partial T}\right)_{P} \cdot
            \left(\frac{\partial T}{\partial V}\right)_{P}
        '''
        return self.dH_dep_dT_l*self.dT_dV_l

    @property
    def dS_dep_dT_l(self):
        r'''Derivative of departure entropy with respect to
        temperature for the liquid phase, [(J/mol)/K^2].

        .. math::
            \frac{\partial S_{dep, l}}{\partial T} = - \frac{R \frac{d}{d T}
            V{\left (T \right )}}{V{\left (T \right )}} + \frac{R \frac{d}{d T}
            V{\left (T \right )}}{- b + V{\left (T \right )}} + \frac{4
            \frac{d}{d T} V{\left (T \right )} \frac{d}{d T} \operatorname{a
            \alpha}{\left (T \right )}}{\left(\delta^{2} - 4 \epsilon\right)
            \left(- \frac{\left(\delta + 2 V{\left (T \right )}\right)^{2}}
            {\delta^{2} - 4 \epsilon} + 1\right)} + \frac{2 \frac{d^{2}}{d
            T^{2}}  \operatorname{a \alpha}{\left (T \right )}}
            {\sqrt{\delta^{2} - 4 \epsilon}} \operatorname{atanh}{\left (\frac{
            \delta + 2 V{\left (T \right )}}{\sqrt{\delta^{2} - 4 \epsilon}}
            \right )} + \frac{R^{2} T}{P V{\left (T \right )}} \left(\frac{P}
            {R T} \frac{d}{d T} V{\left (T \right )} - \frac{P}{R T^{2}}
            V{\left (T \right )}\right)
        '''
        x0 = self.V_l
        x1 = 1./x0
        x2 = self.dV_dT_l
        x3 = R*x2
        x4 = self.a_alpha
        x5 = self.delta*self.delta - 4.0*self.epsilon
        if x5 == 0.0:
            x5 = 1e-100
        x6 = x5**-0.5
        x7 = self.delta + 2.0*x0
        x8 = 1.0/x5
        return (R*x1*(x2 - x0/self.T) - x1*x3 - 4.0*x2*x8*self.da_alpha_dT
                /(x7*x7*x8 - 1.0) - x3/(self.b - x0)
                + 2.0*x6*catanh(x6*x7).real*self.d2a_alpha_dT2)

    @property
    def dS_dep_dT_g(self):
        r'''Derivative of departure entropy with respect to
        temperature for the gas phase, [(J/mol)/K^2].

        .. math::
            \frac{\partial S_{dep, g}}{\partial T} = - \frac{R \frac{d}{d T}
            V{\left (T \right )}}{V{\left (T \right )}} + \frac{R \frac{d}{d T}
            V{\left (T \right )}}{- b + V{\left (T \right )}} + \frac{4
            \frac{d}{d T} V{\left (T \right )} \frac{d}{d T} \operatorname{a
            \alpha}{\left (T \right )}}{\left(\delta^{2} - 4 \epsilon\right)
            \left(- \frac{\left(\delta + 2 V{\left (T \right )}\right)^{2}}
            {\delta^{2} - 4 \epsilon} + 1\right)} + \frac{2 \frac{d^{2}}{d
            T^{2}}  \operatorname{a \alpha}{\left (T \right )}}
            {\sqrt{\delta^{2} - 4 \epsilon}} \operatorname{atanh}{\left (\frac{
            \delta + 2 V{\left (T \right )}}{\sqrt{\delta^{2} - 4 \epsilon}}
            \right )} + \frac{R^{2} T}{P V{\left (T \right )}} \left(\frac{P}
            {R T} \frac{d}{d T} V{\left (T \right )} - \frac{P}{R T^{2}}
            V{\left (T \right )}\right)
        '''
        x0 = self.V_g
        if x0 > 1e50:
            if self.S_dep_g == 0.0:
                return 0.0
        x1 = 1./x0
        x2 = self.dV_dT_g
        if isinf(x2):
            return 0.0
        x3 = R*x2
        x4 = self.a_alpha

        x5 = self.delta*self.delta - 4.0*self.epsilon
        if x5 == 0.0:
            x5 = 1e-100
        x6 = x5**-0.5
        x7 = self.delta + 2.0*x0
        x8 = 1.0/x5
        return (R*x1*(x2 - x0/self.T) - x1*x3 - 4.0*x2*x8*self.da_alpha_dT
                /(x7*x7*x8 - 1.0) - x3/(self.b - x0)
                + 2.0*x6*catanh(x6*x7).real*self.d2a_alpha_dT2)

    @property
    def dS_dep_dT_l_V(self):
        r'''Derivative of departure entropy with respect to
        temperature at constant volume for the liquid phase, [(J/mol)/K^2].

        .. math::
            \left(\frac{\partial S_{dep, l}}{\partial T}\right)_{V} =
            \frac{R^{2} T \left(\frac{V \frac{\partial}{\partial T} P{\left(T,V
            \right)}}{R T} - \frac{V P{\left(T,V \right)}}{R T^{2}}\right)}{
            V P{\left(T,V \right)}} + \frac{2 \operatorname{atanh}{\left(
            \frac{2 V + \delta}{\sqrt{\delta^{2} - 4 \epsilon}} \right)}
            \frac{d^{2}}{d T^{2}} \operatorname{a \alpha}{\left(T \right)}}
            {\sqrt{\delta^{2} - 4 \epsilon}}
        '''
        T, P = self.T, self.P
        delta, epsilon = self.delta, self.epsilon
        V = self.V_l
        dP_dT = self.dP_dT_l
        try:
            x1 = (delta*delta - 4.0*epsilon)**-0.5
        except ZeroDivisionError:
            x1 = 1e100
        return (R*(dP_dT/P - 1.0/T) + 2.0*x1*catanh(x1*(V + V + delta)).real*self.d2a_alpha_dT2)

    @property
    def dS_dep_dT_g_V(self):
        r'''Derivative of departure entropy with respect to
        temperature at constant volume for the gas phase, [(J/mol)/K^2].

        .. math::
            \left(\frac{\partial S_{dep, g}}{\partial T}\right)_{V} =
            \frac{R^{2} T \left(\frac{V \frac{\partial}{\partial T} P{\left(T,V
            \right)}}{R T} - \frac{V P{\left(T,V \right)}}{R T^{2}}\right)}{
            V P{\left(T,V \right)}} + \frac{2 \operatorname{atanh}{\left(
            \frac{2 V + \delta}{\sqrt{\delta^{2} - 4 \epsilon}} \right)}
            \frac{d^{2}}{d T^{2}} \operatorname{a \alpha}{\left(T \right)}}
            {\sqrt{\delta^{2} - 4 \epsilon}}
        '''
        T, P = self.T, self.P
        delta, epsilon = self.delta, self.epsilon
        V = self.V_g
        dP_dT = self.dP_dT_g
        try:
            x1 = (delta*delta - 4.0*epsilon)**-0.5
        except ZeroDivisionError:
            x1 = 1e100
        return (R*(dP_dT/P - 1.0/T) + 2.0*x1*catanh(x1*(V + V + delta)).real*self.d2a_alpha_dT2)

    @property
    def dS_dep_dP_l(self):
        r'''Derivative of departure entropy with respect to
        pressure for the liquid phase, [(J/mol)/K/Pa].

        .. math::
            \frac{\partial S_{dep, l}}{\partial P} = - \frac{R \frac{d}{d P}
            V{\left (P \right )}}{V{\left (P \right )}} + \frac{R \frac{d}{d P}
            V{\left (P \right )}}{- b + V{\left (P \right )}} + \frac{4 \frac{
            d}{d P} V{\left (P \right )} \frac{d}{d T} \operatorname{a \alpha}
            {\left (T \right )}}{\left(\delta^{2} - 4 \epsilon\right) \left(
            - \frac{\left(\delta + 2 V{\left (P \right )}\right)^{2}}{
            \delta^{2} - 4 \epsilon} + 1\right)} + \frac{R^{2} T}{P V{\left (P
            \right )}} \left(\frac{P}{R T} \frac{d}{d P} V{\left (P \right )}
            + \frac{V{\left (P \right )}}{R T}\right)
        '''
        x0 = self.V_l
        x1 = 1.0/x0
        x2 = self.dV_dP_l
        x3 = R*x2
        try:
            x4 = 1.0/(self.delta*self.delta - 4.0*self.epsilon)
        except ZeroDivisionError:
            x4 = 1e50
        return (-x1*x3 - 4.0*x2*x4*self.da_alpha_dT/(x4*(self.delta + 2*x0)**2
                - 1) - x3/(self.b - x0) + R*x1*(self.P*x2 + x0)/self.P)

    @property
    def dS_dep_dP_g(self):
        r'''Derivative of departure entropy with respect to
        pressure for the gas phase, [(J/mol)/K/Pa].

        .. math::
            \frac{\partial S_{dep, g}}{\partial P} = - \frac{R \frac{d}{d P}
            V{\left (P \right )}}{V{\left (P \right )}} + \frac{R \frac{d}{d P}
            V{\left (P \right )}}{- b + V{\left (P \right )}} + \frac{4 \frac{
            d}{d P} V{\left (P \right )} \frac{d}{d T} \operatorname{a \alpha}
            {\left (T \right )}}{\left(\delta^{2} - 4 \epsilon\right) \left(
            - \frac{\left(\delta + 2 V{\left (P \right )}\right)^{2}}{
            \delta^{2} - 4 \epsilon} + 1\right)} + \frac{R^{2} T}{P V{\left (P
            \right )}} \left(\frac{P}{R T} \frac{d}{d P} V{\left (P \right )}
            + \frac{V{\left (P \right )}}{R T}\right)
        '''
        x0 = self.V_g
        x1 = 1.0/x0
        x2 = self.dV_dP_g
        x3 = R*x2
        try:
            x4 = 1.0/(self.delta*self.delta - 4.0*self.epsilon)
        except ZeroDivisionError:
            x4 = 1e200
        ans = (-x1*x3 - 4.0*x2*x4*self.da_alpha_dT/(x4*(self.delta + 2*x0)**2
                - 1) - x3/(self.b - x0) + R*x1*(self.P*x2 + x0)/self.P)
        return ans

    @property
    def dS_dep_dP_g_V(self):
        r'''Derivative of departure entropy with respect to
        pressure at constant volume for the gas phase, [(J/mol)/K/Pa].

        .. math::
            \left(\frac{\partial S_{dep, g}}{\partial P}\right)_{V} =
            \frac{2 \operatorname{atanh}{\left(\frac{2 V + \delta}{
            \sqrt{\delta^{2} - 4 \epsilon}} \right)}
            \left(\frac{\partial \left(\frac{\partial a \alpha}{\partial T}
            \right)_P}{\partial P}\right)_{V}}{\sqrt{\delta^{2} - 4 \epsilon}}
            + \frac{R^{2} \left(- \frac{P V \frac{d}{d P} T{\left(P \right)}}
            {R T^{2}{\left(P \right)}}
             + \frac{V}{R T{\left(P \right)}}\right) T{\left(P \right)}}{P V}
        '''
        T, P, delta, epsilon = self.T, self.P, self.delta, self.epsilon
        d2a_alpha_dT2 = self.d2a_alpha_dT2
        V, dT_dP = self.V_g, self.dT_dP_g
        d2a_alpha_dTdP_V = d2a_alpha_dT2*dT_dP
        try:
            x0 = (delta*delta - 4.0*epsilon)**-0.5
        except ZeroDivisionError:
            x0 = 1e100
        return (2.0*x0*catanh(x0*(V + V + delta)).real*d2a_alpha_dTdP_V
                - R*(P*dT_dP/T - 1.0)/P)

    @property
    def dS_dep_dP_l_V(self):
        r'''Derivative of departure entropy with respect to
        pressure at constant volume for the liquid phase, [(J/mol)/K/Pa].

        .. math::
            \left(\frac{\partial S_{dep, l}}{\partial P}\right)_{V} =
            \frac{2 \operatorname{atanh}{\left(\frac{2 V + \delta}{
            \sqrt{\delta^{2} - 4 \epsilon}} \right)}
            \left(\frac{\partial \left(\frac{\partial a \alpha}{\partial T}
            \right)_P}{\partial P}\right)_{V}}{\sqrt{\delta^{2} - 4 \epsilon}}
            + \frac{R^{2} \left(- \frac{P V \frac{d}{d P} T{\left(P \right)}}
            {R T^{2}{\left(P \right)}}
             + \frac{V}{R T{\left(P \right)}}\right) T{\left(P \right)}}{P V}
        '''
        T, P, delta, epsilon = self.T, self.P, self.delta, self.epsilon
        d2a_alpha_dT2 = self.d2a_alpha_dT2
        V, dT_dP = self.V_l, self.dT_dP_l
        d2a_alpha_dTdP_V = d2a_alpha_dT2*dT_dP
        try:
            x0 = (delta*delta - 4.0*epsilon)**-0.5
        except ZeroDivisionError:
            x0 = 1e100
        return (2.0*x0*catanh(x0*(V + V + delta)).real*d2a_alpha_dTdP_V
                - R*(P*dT_dP/T - 1.0)/P)

    @property
    def dS_dep_dV_g_T(self):
        r'''Derivative of departure entropy with respect to
        volume at constant temperature for the gas phase, [J/K/m^3].

        .. math::
            \left(\frac{\partial S_{dep, g}}{\partial V}\right)_{T} =
            \left(\frac{\partial S_{dep, g}}{\partial P}\right)_{T} \cdot
            \left(\frac{\partial P}{\partial V}\right)_{T}
        '''
        return self.dS_dep_dP_g*self.dP_dV_g

    @property
    def dS_dep_dV_l_T(self):
        r'''Derivative of departure entropy with respect to
        volume at constant temperature for the gas phase, [J/K/m^3].

        .. math::
            \left(\frac{\partial S_{dep, l}}{\partial V}\right)_{T} =
            \left(\frac{\partial S_{dep, l}}{\partial P}\right)_{T} \cdot
            \left(\frac{\partial P}{\partial V}\right)_{T}
        '''
        return self.dS_dep_dP_l*self.dP_dV_l

    @property
    def dS_dep_dV_g_P(self):
        r'''Derivative of departure entropy with respect to
        volume at constant pressure for the gas phase, [J/K/m^3].

        .. math::
            \left(\frac{\partial S_{dep, g}}{\partial V}\right)_{P} =
            \left(\frac{\partial S_{dep, g}}{\partial T}\right)_{P} \cdot
            \left(\frac{\partial T}{\partial V}\right)_{P}
        '''
        return self.dS_dep_dT_g*self.dT_dV_g

    @property
    def dS_dep_dV_l_P(self):
        r'''Derivative of departure entropy with respect to
        volume at constant pressure for the liquid phase, [J/K/m^3].

        .. math::
            \left(\frac{\partial S_{dep, l}}{\partial V}\right)_{P} =
            \left(\frac{\partial S_{dep, l}}{\partial T}\right)_{P} \cdot
            \left(\frac{\partial T}{\partial V}\right)_{P}
        '''
        return self.dS_dep_dT_l*self.dT_dV_l

    @property
    def d2H_dep_dT2_g(self):
        r'''Second temperature derivative of departure enthalpy with respect to
        temperature for the gas phase, [(J/mol)/K^2].

        .. math::
            \frac{\partial^2 H_{dep, g}}{\partial T^2} =
            P \frac{d^{2}}{d T^{2}} V{\left(T \right)} - \frac{8 T \frac{d}{d T}
            V{\left(T \right)} \frac{d^{2}}{d T^{2}} \operatorname{a\alpha}
            {\left(T \right)}}{\left(\delta^{2} - 4 \epsilon\right) \left(\frac{
            \left(\delta + 2 V{\left(T \right)}\right)^{2}}{\delta^{2}
            - 4 \epsilon} - 1\right)} + \frac{2 T \operatorname{atanh}{\left(
            \frac{\delta + 2 V{\left(T \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}} \right)} \frac{d^{3}}{d T^{3}}
            \operatorname{a\alpha}{\left(T \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}} + \frac{16 \left(\delta + 2 V{\left(T \right)}
            \right) \left(T \frac{d}{d T} \operatorname{a\alpha}{\left(T
            \right)} - \operatorname{a\alpha}{\left(T \right)}\right) \left(
            \frac{d}{d T} V{\left(T \right)}\right)^{2}}{\left(\delta^{2}
            - 4 \epsilon\right)^{2} \left(\frac{\left(\delta + 2 V{\left(T
            \right)}\right)^{2}}{\delta^{2} - 4 \epsilon} - 1\right)^{2}}
            - \frac{4 \left(T \frac{d}{d T} \operatorname{a\alpha}{\left(T
            \right)} - \operatorname{a\alpha}{\left(T \right)}\right)
            \frac{d^{2}}{d T^{2}} V{\left(T \right)}}{\left(\delta^{2}
            - 4 \epsilon\right) \left(\frac{\left(\delta + 2 V{\left(T \right)}
            \right)^{2}}{\delta^{2} - 4 \epsilon} - 1\right)} + \frac{2
            \operatorname{atanh}{\left(\frac{\delta + 2 V{\left(T \right)}}
            {\sqrt{\delta^{2} - 4 \epsilon}} \right)} \frac{d^{2}}{d T^{2}}
            \operatorname{a\alpha}{\left(T \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}}
        '''
        T, P, delta, epsilon = self.T, self.P, self.delta, self.epsilon
        x0 = self.V_g
        x1 = self.d2V_dT2_g
        x2 = self.a_alpha
        x3 = self.d2a_alpha_dT2
        x4 = delta*delta - 4.0*epsilon
        try:
            x5 = x4**-0.5
        except:
            x5 = 1e100
        x6 = delta + x0 + x0
        x7 = 2.0*x5*catanh(x5*x6).real
        x8 = self.dV_dT_g
        x9 = x5*x5
        x10 = x6*x6*x9 - 1.0
        x11 = x9/x10
        x12 = T*self.da_alpha_dT - x2
        x50 = self.d3a_alpha_dT3
        return (P*x1  + x3*x7  + T*x7*x50- 4.0*x1*x11*x12  - 8.0*T*x11*x3*x8 + 16.0*x12*x6*x8*x8*x11*x11)

    d2H_dep_dT2_g_P = d2H_dep_dT2_g

    @property
    def d2H_dep_dT2_l(self):
        r'''Second temperature derivative of departure enthalpy with respect to
        temperature for the liquid phase, [(J/mol)/K^2].

        .. math::
            \frac{\partial^2 H_{dep, l}}{\partial T^2} =
            P \frac{d^{2}}{d T^{2}} V{\left(T \right)} - \frac{8 T \frac{d}{d T}
            V{\left(T \right)} \frac{d^{2}}{d T^{2}} \operatorname{a\alpha}
            {\left(T \right)}}{\left(\delta^{2} - 4 \epsilon\right) \left(\frac{
            \left(\delta + 2 V{\left(T \right)}\right)^{2}}{\delta^{2}
            - 4 \epsilon} - 1\right)} + \frac{2 T \operatorname{atanh}{\left(
            \frac{\delta + 2 V{\left(T \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}} \right)} \frac{d^{3}}{d T^{3}}
            \operatorname{a\alpha}{\left(T \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}} + \frac{16 \left(\delta + 2 V{\left(T \right)}
            \right) \left(T \frac{d}{d T} \operatorname{a\alpha}{\left(T
            \right)} - \operatorname{a\alpha}{\left(T \right)}\right) \left(
            \frac{d}{d T} V{\left(T \right)}\right)^{2}}{\left(\delta^{2}
            - 4 \epsilon\right)^{2} \left(\frac{\left(\delta + 2 V{\left(T
            \right)}\right)^{2}}{\delta^{2} - 4 \epsilon} - 1\right)^{2}}
            - \frac{4 \left(T \frac{d}{d T} \operatorname{a\alpha}{\left(T
            \right)} - \operatorname{a\alpha}{\left(T \right)}\right)
            \frac{d^{2}}{d T^{2}} V{\left(T \right)}}{\left(\delta^{2}
            - 4 \epsilon\right) \left(\frac{\left(\delta + 2 V{\left(T \right)}
            \right)^{2}}{\delta^{2} - 4 \epsilon} - 1\right)} + \frac{2
            \operatorname{atanh}{\left(\frac{\delta + 2 V{\left(T \right)}}
            {\sqrt{\delta^{2} - 4 \epsilon}} \right)} \frac{d^{2}}{d T^{2}}
            \operatorname{a\alpha}{\left(T \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}}
        '''
        T, P, delta, epsilon = self.T, self.P, self.delta, self.epsilon
        x0 = self.V_l
        x1 = self.d2V_dT2_l
        x2 = self.a_alpha
        x3 = self.d2a_alpha_dT2
        x4 = delta*delta - 4.0*epsilon
        try:
            x5 = x4**-0.5
        except:
            x5 = 1e100
        x6 = delta + x0 + x0
        x7 = 2.0*x5*catanh(x5*x6).real
        x8 = self.dV_dT_l
        x9 = x5*x5
        x10 = x6*x6*x9 - 1.0
        x11 = x9/x10
        x12 = T*self.da_alpha_dT - x2
        x50 = self.d3a_alpha_dT3
        return (P*x1  + x3*x7  + T*x7*x50- 4.0*x1*x11*x12  - 8.0*T*x11*x3*x8 + 16.0*x12*x6*x8*x8*x11*x11)

    d2H_dep_dT2_l_P = d2H_dep_dT2_l

    @property
    def d2S_dep_dT2_g(self):
        r'''Second temperature derivative of departure entropy with respect to
        temperature for the gas phase, [(J/mol)/K^3].

        .. math::
            \frac{\partial^2 S_{dep, g}}{\partial T^2} = - \frac{R \left(
            \frac{d}{d T} V{\left(T \right)} - \frac{V{\left(T \right)}}{T}
            \right) \frac{d}{d T} V{\left(T \right)}}{V^{2}{\left(T \right)}}
            + \frac{R \left(\frac{d^{2}}{d T^{2}} V{\left(T \right)}
            - \frac{2 \frac{d}{d T} V{\left(T \right)}}{T} + \frac{2
            V{\left(T \right)}}{T^{2}}\right)}{V{\left(T \right)}}
            - \frac{R \frac{d^{2}}{d T^{2}} V{\left(T \right)}}{V{\left(T
            \right)}} + \frac{R \left(\frac{d}{d T} V{\left(T \right)}
            \right)^{2}}{V^{2}{\left(T \right)}} - \frac{R \frac{d^{2}}{dT^{2}}
            V{\left(T \right)}}{b - V{\left(T \right)}} - \frac{R \left(
            \frac{d}{d T} V{\left(T \right)}\right)^{2}}{\left(b - V{\left(T
            \right)}\right)^{2}} + \frac{R \left(\frac{d}{d T} V{\left(T
            \right)} - \frac{V{\left(T \right)}}{T}\right)}{T V{\left(T
            \right)}} + \frac{16 \left(\delta + 2 V{\left(T \right)}\right)
            \left(\frac{d}{d T} V{\left(T \right)}\right)^{2} \frac{d}{d T}
            \operatorname{a\alpha}{\left(T \right)}}{\left(\delta^{2}
            - 4 \epsilon\right)^{2} \left(\frac{\left(\delta + 2 V{\left(T
            \right)}\right)^{2}}{\delta^{2} - 4 \epsilon} - 1\right)^{2}}
            - \frac{8 \frac{d}{d T} V{\left(T \right)} \frac{d^{2}}{d T^{2}}
            \operatorname{a\alpha}{\left(T \right)}}{\left(\delta^{2}
            - 4 \epsilon\right) \left(\frac{\left(\delta + 2 V{\left(T \right)}
            \right)^{2}}{\delta^{2} - 4 \epsilon} - 1\right)} - \frac{4
            \frac{d^{2}}{d T^{2}} V{\left(T \right)} \frac{d}{d T}
            \operatorname{a\alpha}{\left(T \right)}}{\left(\delta^{2}
            - 4 \epsilon\right) \left(\frac{\left(\delta + 2 V{\left(T \right)}
            \right)^{2}}{\delta^{2} - 4 \epsilon} - 1\right)} + \frac{2
            \operatorname{atanh}{\left(\frac{\delta + 2 V{\left(T
            \right)}}{\sqrt{\delta^{2} - 4 \epsilon}} \right)} \frac{d^{3}}
            {d T^{3}} \operatorname{a\alpha}{\left(T \right)}}
            {\sqrt{\delta^{2} - 4 \epsilon}}
        '''
        T, P, b, delta, epsilon = self.T, self.P, self.b, self.delta, self.epsilon
        V = x0 = self.V_g
        V_inv = 1.0/V
        x1 = self.d2V_dT2_g
        x2 = R*V_inv
        x3 = V_inv*V_inv
        x4 = self.dV_dT_g
        x5 = x4*x4
        x6 = R*x5
        x7 = b - x0
        x8 = 1.0/T
        x9 = -x0*x8 + x4
        x10 = x0 + x0
        x11 = self.a_alpha
        x12 = delta*delta - 4.0*epsilon
        try:
            x13 = x12**-0.5
        except ZeroDivisionError:
            x13 = 1e100
        x14 = delta + x10
        x15 = x13*x13
        x16 = x14*x14*x15 - 1.0
        x51 = 1.0/x16
        x17 = x15*x51
        x18 = self.da_alpha_dT
        x50 = 1.0/x7
        d2a_alpha_dT2 = self.d2a_alpha_dT2
        d3a_alpha_dT3 = self.d3a_alpha_dT3
        return (-R*x1*x50 - R*x3*x4*x9 - 4.0*x1*x17*x18 - x1*x2
                + 2.0*x13*catanh(x13*x14).real*d3a_alpha_dT3
                - 8.0*x17*x4*d2a_alpha_dT2 + x2*x8*x9
                + x2*(x1 - 2.0*x4*x8 + x10*x8*x8) + x3*x6 - x6*x50*x50
                + 16.0*x14*x18*x5*x51*x51*x15*x15)

    @property
    def d2S_dep_dT2_l(self):
        r'''Second temperature derivative of departure entropy with respect to
        temperature for the liquid phase, [(J/mol)/K^3].

        .. math::
            \frac{\partial^2 S_{dep, l}}{\partial T^2} = - \frac{R \left(
            \frac{d}{d T} V{\left(T \right)} - \frac{V{\left(T \right)}}{T}
            \right) \frac{d}{d T} V{\left(T \right)}}{V^{2}{\left(T \right)}}
            + \frac{R \left(\frac{d^{2}}{d T^{2}} V{\left(T \right)}
            - \frac{2 \frac{d}{d T} V{\left(T \right)}}{T} + \frac{2
            V{\left(T \right)}}{T^{2}}\right)}{V{\left(T \right)}}
            - \frac{R \frac{d^{2}}{d T^{2}} V{\left(T \right)}}{V{\left(T
            \right)}} + \frac{R \left(\frac{d}{d T} V{\left(T \right)}
            \right)^{2}}{V^{2}{\left(T \right)}} - \frac{R \frac{d^{2}}{dT^{2}}
            V{\left(T \right)}}{b - V{\left(T \right)}} - \frac{R \left(
            \frac{d}{d T} V{\left(T \right)}\right)^{2}}{\left(b - V{\left(T
            \right)}\right)^{2}} + \frac{R \left(\frac{d}{d T} V{\left(T
            \right)} - \frac{V{\left(T \right)}}{T}\right)}{T V{\left(T
            \right)}} + \frac{16 \left(\delta + 2 V{\left(T \right)}\right)
            \left(\frac{d}{d T} V{\left(T \right)}\right)^{2} \frac{d}{d T}
            \operatorname{a\alpha}{\left(T \right)}}{\left(\delta^{2}
            - 4 \epsilon\right)^{2} \left(\frac{\left(\delta + 2 V{\left(T
            \right)}\right)^{2}}{\delta^{2} - 4 \epsilon} - 1\right)^{2}}
            - \frac{8 \frac{d}{d T} V{\left(T \right)} \frac{d^{2}}{d T^{2}}
            \operatorname{a\alpha}{\left(T \right)}}{\left(\delta^{2}
            - 4 \epsilon\right) \left(\frac{\left(\delta + 2 V{\left(T \right)}
            \right)^{2}}{\delta^{2} - 4 \epsilon} - 1\right)} - \frac{4
            \frac{d^{2}}{d T^{2}} V{\left(T \right)} \frac{d}{d T}
            \operatorname{a\alpha}{\left(T \right)}}{\left(\delta^{2}
            - 4 \epsilon\right) \left(\frac{\left(\delta + 2 V{\left(T \right)}
            \right)^{2}}{\delta^{2} - 4 \epsilon} - 1\right)} + \frac{2
            \operatorname{atanh}{\left(\frac{\delta + 2 V{\left(T
            \right)}}{\sqrt{\delta^{2} - 4 \epsilon}} \right)} \frac{d^{3}}
            {d T^{3}} \operatorname{a\alpha}{\left(T \right)}}
            {\sqrt{\delta^{2} - 4 \epsilon}}
        '''
        T, P, b, delta, epsilon = self.T, self.P, self.b, self.delta, self.epsilon
        V = x0 = self.V_l
        V_inv = 1.0/V
        x1 = self.d2V_dT2_l
        x2 = R*V_inv
        x3 = V_inv*V_inv
        x4 = self.dV_dT_l
        x5 = x4*x4
        x6 = R*x5
        x7 = b - x0
        x8 = 1.0/T
        x9 = -x0*x8 + x4
        x10 = x0 + x0
        x11 = self.a_alpha
        x12 = delta*delta - 4.0*epsilon
        try:
            x13 = x12**-0.5
        except ZeroDivisionError:
            x13 = 1e100
        x14 = delta + x10
        x15 = x13*x13
        x16 = x14*x14*x15 - 1.0
        x51 = 1.0/x16
        x17 = x15*x51
        x18 = self.da_alpha_dT
        x50 = 1.0/x7
        d2a_alpha_dT2 = self.d2a_alpha_dT2
        d3a_alpha_dT3 = self.d3a_alpha_dT3
        return (-R*x1*x50 - R*x3*x4*x9 - 4.0*x1*x17*x18 - x1*x2
                + 2.0*x13*catanh(x13*x14).real*d3a_alpha_dT3
                - 8.0*x17*x4*d2a_alpha_dT2 + x2*x8*x9
                + x2*(x1 - 2.0*x4*x8 + x10*x8*x8) + x3*x6 - x6*x50*x50
                + 16.0*x14*x18*x5*x51*x51*x15*x15)

    @property
    def d2H_dep_dT2_g_V(self):
        r'''Second temperature derivative of departure enthalpy with respect to
        temperature at constant volume for the gas phase, [(J/mol)/K^2].

        .. math::
            \left(\frac{\partial^2 H_{dep, g}}{\partial T^2}\right)_V =
            \frac{2 T \operatorname{atanh}{\left(\frac{2 V + \delta}{\sqrt{
            \delta^{2} - 4 \epsilon}} \right)} \frac{d^{3}}{d T^{3}}
            \operatorname{a\alpha}{\left(T \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}} + V \frac{\partial^{2}}{\partial T^{2}}
            P{\left(V,T \right)} + \frac{2 \operatorname{atanh}{\left(\frac{
            2 V + \delta}{\sqrt{\delta^{2} - 4 \epsilon}} \right)} \frac{d^{2}}
            {d T^{2}} \operatorname{a\alpha}{\left(T \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}}
        '''
        V, T, delta, epsilon = self.V_g, self.T, self.delta, self.epsilon
        x51 = delta*delta - 4.0*epsilon
        d2a_alpha_dT2 = self.d2a_alpha_dT2
        d3a_alpha_dT3 = self.d3a_alpha_dT3
        d2P_dT2 = self.d2P_dT2_g
        try:
            x1 = x51**-0.5
        except ZeroDivisionError:
            x1 = 1e100
        x2 = 2.0*x1*catanh(x1*(V + V + delta)).real
        return T*x2*d3a_alpha_dT3 + V*d2P_dT2 + x2*d2a_alpha_dT2

    @property
    def d2H_dep_dT2_l_V(self):
        r'''Second temperature derivative of departure enthalpy with respect to
        temperature at constant volume for the liquid phase, [(J/mol)/K^2].

        .. math::
            \left(\frac{\partial^2 H_{dep, l}}{\partial T^2}\right)_V =
            \frac{2 T \operatorname{atanh}{\left(\frac{2 V + \delta}{\sqrt{
            \delta^{2} - 4 \epsilon}} \right)} \frac{d^{3}}{d T^{3}}
            \operatorname{a\alpha}{\left(T \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}} + V \frac{\partial^{2}}{\partial T^{2}}
            P{\left(V,T \right)} + \frac{2 \operatorname{atanh}{\left(\frac{
            2 V + \delta}{\sqrt{\delta^{2} - 4 \epsilon}} \right)} \frac{d^{2}}
            {d T^{2}} \operatorname{a\alpha}{\left(T \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}}
        '''
        V, T, delta, epsilon = self.V_l, self.T, self.delta, self.epsilon
        x51 = delta*delta - 4.0*epsilon
        d2a_alpha_dT2 = self.d2a_alpha_dT2
        d3a_alpha_dT3 = self.d3a_alpha_dT3
        d2P_dT2 = self.d2P_dT2_l
        try:
            x1 = x51**-0.5
        except ZeroDivisionError:
            x1 = 1e100
        x2 = 2.0*x1*catanh(x1*(V + V + delta)).real
        return T*x2*d3a_alpha_dT3 + V*d2P_dT2 + x2*d2a_alpha_dT2

    @property
    def d2S_dep_dT2_g_V(self):
        r'''Second temperature derivative of departure entropy with respect to
        temperature at constant volume for the gas phase, [(J/mol)/K^3].

        .. math::
            \left(\frac{\partial^2 S_{dep, g}}{\partial T^2}\right)_V =
            - \frac{R \left(\frac{\partial}{\partial T} P{\left(V,T \right)}
            - \frac{P{\left(V,T \right)}}{T}\right) \frac{\partial}{\partial T}
            P{\left(V,T \right)}}{P^{2}{\left(V,T \right)}} + \frac{R \left(
            \frac{\partial^{2}}{\partial T^{2}} P{\left(V,T \right)} - \frac{2
            \frac{\partial}{\partial T} P{\left(V,T \right)}}{T} + \frac{2
            P{\left(V,T \right)}}{T^{2}}\right)}{P{\left(V,T \right)}}
            + \frac{R \left(\frac{\partial}{\partial T} P{\left(V,T \right)}
            - \frac{P{\left(V,T \right)}}{T}\right)}{T P{\left(V,T \right)}}
            + \frac{2 \operatorname{atanh}{\left(\frac{2 V + \delta}{\sqrt{
            \delta^{2} - 4 \epsilon}} \right)} \frac{d^{3}}{d T^{3}}
            \operatorname{a\alpha}{\left(T \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}}
        '''
        V, T, delta, epsilon = self.V_g, self.T, self.delta, self.epsilon
        d2a_alpha_dT2 = self.d2a_alpha_dT2
        d3a_alpha_dT3 = self.d3a_alpha_dT3
        d2P_dT2 = self.d2P_dT2_g

        x0 = 1.0/T
        x1 = self.P
        P_inv = 1.0/x1
        x2 = self.dP_dT_g
        x3 = -x0*x1 + x2
        x4 = R*P_inv
        try:
            x5 = (delta*delta - 4.0*epsilon)**-0.5
        except ZeroDivisionError:
            x5 = 1e100
        return (-R*x2*x3*P_inv*P_inv + x0*x3*x4 + x4*(d2P_dT2 - 2.0*x0*x2
                + 2.0*x1*x0*x0) + 2.0*x5*catanh(x5*(V + V + delta)
                ).real*d3a_alpha_dT3)

    @property
    def d2S_dep_dT2_l_V(self):
        r'''Second temperature derivative of departure entropy with respect to
        temperature at constant volume for the liquid phase, [(J/mol)/K^3].

        .. math::
            \left(\frac{\partial^2 S_{dep, l}}{\partial T^2}\right)_V =
            - \frac{R \left(\frac{\partial}{\partial T} P{\left(V,T \right)}
            - \frac{P{\left(V,T \right)}}{T}\right) \frac{\partial}{\partial T}
            P{\left(V,T \right)}}{P^{2}{\left(V,T \right)}} + \frac{R \left(
            \frac{\partial^{2}}{\partial T^{2}} P{\left(V,T \right)} - \frac{2
            \frac{\partial}{\partial T} P{\left(V,T \right)}}{T} + \frac{2
            P{\left(V,T \right)}}{T^{2}}\right)}{P{\left(V,T \right)}}
            + \frac{R \left(\frac{\partial}{\partial T} P{\left(V,T \right)}
            - \frac{P{\left(V,T \right)}}{T}\right)}{T P{\left(V,T \right)}}
            + \frac{2 \operatorname{atanh}{\left(\frac{2 V + \delta}{\sqrt{
            \delta^{2} - 4 \epsilon}} \right)} \frac{d^{3}}{d T^{3}}
            \operatorname{a\alpha}{\left(T \right)}}{\sqrt{\delta^{2}
            - 4 \epsilon}}
        '''
        V, T, delta, epsilon = self.V_l, self.T, self.delta, self.epsilon
        d2a_alpha_dT2 = self.d2a_alpha_dT2
        d3a_alpha_dT3 = self.d3a_alpha_dT3
        d2P_dT2 = self.d2P_dT2_l
        x0 = 1.0/T
        x1 = self.P
        P_inv = 1.0/x1
        x2 = self.dP_dT_l
        x3 = -x0*x1 + x2
        x4 = R*P_inv
        try:
            x5 = (delta*delta - 4.0*epsilon)**-0.5
        except ZeroDivisionError:
            x5 = 1e100
        return (-R*x2*x3*P_inv*P_inv + x0*x3*x4 + x4*(d2P_dT2 - 2.0*x0*x2
                + 2.0*x1*x0*x0) + 2.0*x5*catanh(x5*(V + V + delta)
                ).real*d3a_alpha_dT3)

    @property
    def d2H_dep_dTdP_g(self):
        r'''Temperature and pressure derivative of departure enthalpy
        at constant pressure then temperature for the gas phase,
        [(J/mol)/K/Pa].

        .. math::
            \left(\frac{\partial^2 H_{dep, g}}{\partial T \partial P}\right)_{T, P}
            = P \frac{\partial^{2}}{\partial T\partial P} V{\left(T,P \right)}
            - \frac{4 T \frac{\partial}{\partial P} V{\left(T,P \right)}
            \frac{d^{2}}{d T^{2}} \operatorname{a\alpha}{\left(T \right)}}
            {\left(\delta^{2} - 4 \epsilon\right) \left(\frac{\left(\delta
            + 2 V{\left(T,P \right)}\right)^{2}}{\delta^{2} - 4 \epsilon}
            - 1\right)} + \frac{16 \left(\delta + 2 V{\left(T,P \right)}\right)
            \left(T \frac{d}{d T} \operatorname{a\alpha}{\left(T \right)}
            - \operatorname{a\alpha}{\left(T \right)}\right) \frac{\partial}
            {\partial P} V{\left(T,P \right)} \frac{\partial}{\partial T}
            V{\left(T,P \right)}}{\left(\delta^{2} - 4 \epsilon\right)^{2}
            \left(\frac{\left(\delta + 2 V{\left(T,P \right)}\right)^{2}}
            {\delta^{2} - 4 \epsilon} - 1\right)^{2}} + \frac{\partial}
            {\partial T} V{\left(T,P \right)} - \frac{4 \left(T \frac{d}{d T}
            \operatorname{a\alpha}{\left(T \right)} - \operatorname{a\alpha}
            {\left(T \right)}\right) \frac{\partial^{2}}{\partial T\partial P}
            V{\left(T,P \right)}}{\left(\delta^{2} - 4 \epsilon\right)
            \left(\frac{\left(\delta + 2 V{\left(T,P \right)}\right)^{2}}
            {\delta^{2} - 4 \epsilon} - 1\right)}
        '''
        V, T, P, delta, epsilon = self.V_g, self.T, self.P, self.delta, self.epsilon
        dV_dT = self.dV_dT_g
        d2V_dTdP = self.d2V_dTdP_g
        dV_dP = self.dV_dP_g
        a_alpha = self.a_alpha
        d2a_alpha_dT2 = self.d2a_alpha_dT2
        x5 = delta*delta - 4.0*epsilon
        try:
            x6 = 1.0/x5
        except ZeroDivisionError:
            x6 = 1e100
        x7 = delta + V  + V
        x8 = x6*x7*x7 - 1.0
        x8_inv = 1.0/x8
        x9 = 4.0*x6*x8_inv
        x10 = T*self.da_alpha_dT - a_alpha
        return (P*d2V_dTdP - T*dV_dP*x9*d2a_alpha_dT2
                + 16.0*dV_dT*x10*dV_dP*x7*x6*x6*x8_inv*x8_inv
                + dV_dT - x10*d2V_dTdP*x9)

    @property
    def d2H_dep_dTdP_l(self):
        r'''Temperature and pressure derivative of departure enthalpy
        at constant pressure then temperature for the liquid phase,
        [(J/mol)/K/Pa].

        .. math::
            \left(\frac{\partial^2 H_{dep, l}}{\partial T \partial P}\right)_V
            = P \frac{\partial^{2}}{\partial T\partial P} V{\left(T,P \right)}
            - \frac{4 T \frac{\partial}{\partial P} V{\left(T,P \right)}
            \frac{d^{2}}{d T^{2}} \operatorname{a\alpha}{\left(T \right)}}
            {\left(\delta^{2} - 4 \epsilon\right) \left(\frac{\left(\delta
            + 2 V{\left(T,P \right)}\right)^{2}}{\delta^{2} - 4 \epsilon}
            - 1\right)} + \frac{16 \left(\delta + 2 V{\left(T,P \right)}\right)
            \left(T \frac{d}{d T} \operatorname{a\alpha}{\left(T \right)}
            - \operatorname{a\alpha}{\left(T \right)}\right) \frac{\partial}
            {\partial P} V{\left(T,P \right)} \frac{\partial}{\partial T}
            V{\left(T,P \right)}}{\left(\delta^{2} - 4 \epsilon\right)^{2}
            \left(\frac{\left(\delta + 2 V{\left(T,P \right)}\right)^{2}}
            {\delta^{2} - 4 \epsilon} - 1\right)^{2}} + \frac{\partial}
            {\partial T} V{\left(T,P \right)} - \frac{4 \left(T \frac{d}{d T}
            \operatorname{a\alpha}{\left(T \right)} - \operatorname{a\alpha}
            {\left(T \right)}\right) \frac{\partial^{2}}{\partial T\partial P}
            V{\left(T,P \right)}}{\left(\delta^{2} - 4 \epsilon\right)
            \left(\frac{\left(\delta + 2 V{\left(T,P \right)}\right)^{2}}
            {\delta^{2} - 4 \epsilon} - 1\right)}
        '''
        V, T, P, delta, epsilon = self.V_l, self.T, self.P, self.delta, self.epsilon
        dV_dT = self.dV_dT_l
        d2V_dTdP = self.d2V_dTdP_l
        dV_dP = self.dV_dP_l
        a_alpha = self.a_alpha
        d2a_alpha_dT2 = self.d2a_alpha_dT2
        x5 = delta*delta - 4.0*epsilon
        try:
            x6 = 1.0/x5
        except ZeroDivisionError:
            x6 = 1e100
        x7 = delta + V  + V
        x8 = x6*x7*x7 - 1.0
        x8_inv = 1.0/x8
        x9 = 4.0*x6*x8_inv
        x10 = T*self.da_alpha_dT - a_alpha
        return (P*d2V_dTdP - T*dV_dP*x9*d2a_alpha_dT2
                + 16.0*dV_dT*x10*dV_dP*x7*x6*x6*x8_inv*x8_inv
                + dV_dT - x10*d2V_dTdP*x9)

    @property
    def d2S_dep_dTdP_g(self):
        r'''Temperature and pressure derivative of departure entropy
        at constant pressure then temperature for the gas phase,
        [(J/mol)/K^2/Pa].

        .. math::
            \left(\frac{\partial^2 S_{dep, g}}{\partial T \partial P}\right)_{T, P}
            = - \frac{R \frac{\partial^{2}}{\partial T\partial P} V{\left(T,P
            \right)}}{V{\left(T,P \right)}} + \frac{R \frac{\partial}{\partial
            P} V{\left(T,P \right)} \frac{\partial}{\partial T} V{\left(T,P
            \right)}}{V^{2}{\left(T,P \right)}} - \frac{R \frac{\partial^{2}}
            {\partial T\partial P} V{\left(T,P \right)}}{b - V{\left(T,P
            \right)}} - \frac{R \frac{\partial}{\partial P} V{\left(T,P
            \right)} \frac{\partial}{\partial T} V{\left(T,P \right)}}{\left(b
            - V{\left(T,P \right)}\right)^{2}} + \frac{16 \left(\delta
            + 2 V{\left(T,P \right)}\right) \frac{\partial}{\partial P}
            V{\left(T,P \right)} \frac{\partial}{\partial T} V{\left(T,P
            \right)} \frac{d}{d T} \operatorname{a\alpha}{\left(T \right)}}
            {\left(\delta^{2} - 4 \epsilon\right)^{2} \left(\frac{\left(\delta
            + 2 V{\left(T,P \right)}\right)^{2}}{\delta^{2} - 4 \epsilon}
            - 1\right)^{2}} - \frac{4 \frac{\partial}{\partial P} V{\left(T,P
            \right)} \frac{d^{2}}{d T^{2}} \operatorname{a\alpha}{\left(T
            \right)}}{\left(\delta^{2} - 4 \epsilon\right) \left(\frac{\left(
            \delta + 2 V{\left(T,P \right)}\right)^{2}}{\delta^{2}
            - 4 \epsilon} - 1\right)} - \frac{4 \frac{d}{d T}
            \operatorname{a\alpha}{\left(T \right)} \frac{\partial^{2}}
            {\partial T\partial P} V{\left(T,P \right)}}{\left(\delta^{2}
            - 4 \epsilon\right) \left(\frac{\left(\delta + 2 V{\left(T,P
            \right)}\right)^{2}}{\delta^{2} - 4 \epsilon} - 1\right)}
            - \frac{R \left(P \frac{\partial}{\partial P} V{\left(T,P \right)}
            + V{\left(T,P \right)}\right) \frac{\partial}{\partial T}
            V{\left(T,P \right)}}{P V^{2}{\left(T,P \right)}} + \frac{R
            \left(P \frac{\partial^{2}}{\partial T\partial P} V{\left(T,P
            \right)} - \frac{P \frac{\partial}{\partial P} V{\left(T,P
            \right)}}{T} + \frac{\partial}{\partial T} V{\left(T,P \right)}
            - \frac{V{\left(T,P \right)}}{T}\right)}{P V{\left(T,P \right)}}
            + \frac{R \left(P \frac{\partial}{\partial P} V{\left(T,P \right)}
            + V{\left(T,P \right)}\right)}{P T V{\left(T,P \right)}}
        '''
        V, T, P, b, delta, epsilon = self.V_g, self.T, self.P, self.b, self.delta, self.epsilon
        dV_dT = self.dV_dT_g
        d2V_dTdP = self.d2V_dTdP_g
        dV_dP = self.dV_dP_g

        x0 = V
        V_inv = 1.0/V
        x2 = d2V_dTdP
        x3 = R*x2
        x4 = dV_dT
        x5 = x4*V_inv*V_inv
        x6 = dV_dP
        x7 = R*x6
        x8 = b - V
        x8_inv = 1.0/x8
        x9 = 1.0/T
        x10 = P*x6
        x11 = V + x10
        x12 = R/P
        x13 = V_inv*x12
        x14 = self.a_alpha
        x15 = delta*delta - 4.0*epsilon
        try:
            x16 = 1.0/x15
        except ZeroDivisionError:
            x16 = 1e100
        x17 = delta + V + V
        x18 = x16*x17*x17 - 1.0
        x50 = 1.0/x18
        x19 = 4.0*x16*x50
        x20 = self.da_alpha_dT
        return (-V_inv*x3 - x11*x12*x5 + x11*x13*x9 + x13*(P*x2 - V*x9 - x10*x9
                + x4) - x19*x2*x20 - x19*x6*self.d2a_alpha_dT2 - x3*x8_inv
                - x4*x7*x8_inv*x8_inv + x5*x7
                + 16.0*x17*x20*x4*x6*x16*x16*x50*x50)

    @property
    def d2S_dep_dTdP_l(self):
        r'''Temperature and pressure derivative of departure entropy
        at constant pressure then temperature for the liquid phase,
        [(J/mol)/K^2/Pa].

        .. math::
            \left(\frac{\partial^2 S_{dep, l}}{\partial T \partial P}\right)_{T, P}
            = - \frac{R \frac{\partial^{2}}{\partial T\partial P} V{\left(T,P
            \right)}}{V{\left(T,P \right)}} + \frac{R \frac{\partial}{\partial
            P} V{\left(T,P \right)} \frac{\partial}{\partial T} V{\left(T,P
            \right)}}{V^{2}{\left(T,P \right)}} - \frac{R \frac{\partial^{2}}
            {\partial T\partial P} V{\left(T,P \right)}}{b - V{\left(T,P
            \right)}} - \frac{R \frac{\partial}{\partial P} V{\left(T,P
            \right)} \frac{\partial}{\partial T} V{\left(T,P \right)}}{\left(b
            - V{\left(T,P \right)}\right)^{2}} + \frac{16 \left(\delta
            + 2 V{\left(T,P \right)}\right) \frac{\partial}{\partial P}
            V{\left(T,P \right)} \frac{\partial}{\partial T} V{\left(T,P
            \right)} \frac{d}{d T} \operatorname{a\alpha}{\left(T \right)}}
            {\left(\delta^{2} - 4 \epsilon\right)^{2} \left(\frac{\left(\delta
            + 2 V{\left(T,P \right)}\right)^{2}}{\delta^{2} - 4 \epsilon}
            - 1\right)^{2}} - \frac{4 \frac{\partial}{\partial P} V{\left(T,P
            \right)} \frac{d^{2}}{d T^{2}} \operatorname{a\alpha}{\left(T
            \right)}}{\left(\delta^{2} - 4 \epsilon\right) \left(\frac{\left(
            \delta + 2 V{\left(T,P \right)}\right)^{2}}{\delta^{2}
            - 4 \epsilon} - 1\right)} - \frac{4 \frac{d}{d T}
            \operatorname{a\alpha}{\left(T \right)} \frac{\partial^{2}}
            {\partial T\partial P} V{\left(T,P \right)}}{\left(\delta^{2}
            - 4 \epsilon\right) \left(\frac{\left(\delta + 2 V{\left(T,P
            \right)}\right)^{2}}{\delta^{2} - 4 \epsilon} - 1\right)}
            - \frac{R \left(P \frac{\partial}{\partial P} V{\left(T,P \right)}
            + V{\left(T,P \right)}\right) \frac{\partial}{\partial T}
            V{\left(T,P \right)}}{P V^{2}{\left(T,P \right)}} + \frac{R
            \left(P \frac{\partial^{2}}{\partial T\partial P} V{\left(T,P
            \right)} - \frac{P \frac{\partial}{\partial P} V{\left(T,P
            \right)}}{T} + \frac{\partial}{\partial T} V{\left(T,P \right)}
            - \frac{V{\left(T,P \right)}}{T}\right)}{P V{\left(T,P \right)}}
            + \frac{R \left(P \frac{\partial}{\partial P} V{\left(T,P \right)}
            + V{\left(T,P \right)}\right)}{P T V{\left(T,P \right)}}
        '''
        V, T, P, b, delta, epsilon = self.V_l, self.T, self.P, self.b, self.delta, self.epsilon
        dV_dT = self.dV_dT_l
        d2V_dTdP = self.d2V_dTdP_l
        dV_dP = self.dV_dP_l

        x0 = V
        V_inv = 1.0/V
        x2 = d2V_dTdP
        x3 = R*x2
        x4 = dV_dT
        x5 = x4*V_inv*V_inv
        x6 = dV_dP
        x7 = R*x6
        x8 = b - V
        x8_inv = 1.0/x8
        x9 = 1.0/T
        x10 = P*x6
        x11 = V + x10
        x12 = R/P
        x13 = V_inv*x12
        x14 = self.a_alpha
        x15 = delta*delta - 4.0*epsilon
        try:
            x16 = 1.0/x15
        except ZeroDivisionError:
            x16 = 1e100
        x17 = delta + V + V
        x18 = x16*x17*x17 - 1.0
        x50 = 1.0/x18
        x19 = 4.0*x16*x50
        x20 = self.da_alpha_dT
        return (-V_inv*x3 - x11*x12*x5 + x11*x13*x9 + x13*(P*x2 - V*x9 - x10*x9
                + x4) - x19*x2*x20 - x19*x6*self.d2a_alpha_dT2 - x3*x8_inv
                - x4*x7*x8_inv*x8_inv + x5*x7
                + 16.0*x17*x20*x4*x6*x16*x16*x50*x50)

    @property
    def dfugacity_dT_l(self):
        r'''Derivative of fugacity with respect to temperature for the liquid
        phase, [Pa/K].

        .. math::
            \frac{\partial (\text{fugacity})_{l}}{\partial T} = P \left(\frac{1}
            {R T} \left(- T \frac{\partial}{\partial T} \operatorname{S_{dep}}
            {\left (T,P \right )} - \operatorname{S_{dep}}{\left (T,P \right )}
            + \frac{\partial}{\partial T} \operatorname{H_{dep}}{\left (T,P
            \right )}\right) - \frac{1}{R T^{2}} \left(- T \operatorname{
                S_{dep}}{\left (T,P \right )} + \operatorname{H_{dep}}{\left
                (T,P \right )}\right)\right) e^{\frac{1}{R T} \left(- T
                \operatorname{S_{dep}}{\left (T,P \right )} + \operatorname
                {H_{dep}}{\left (T,P \right )}\right)}
        '''
        T, P = self.T, self.P
        T_inv = 1.0/T
        S_dep_l = self.S_dep_l
        x4 = R_inv*(self.H_dep_l - T*S_dep_l)
        return P*(T_inv*R_inv*(self.dH_dep_dT_l - T*self.dS_dep_dT_l - S_dep_l)
                  - x4*T_inv*T_inv)*exp(T_inv*x4)

    @property
    def dfugacity_dT_g(self):
        r'''Derivative of fugacity with respect to temperature for the gas
        phase, [Pa/K].

        .. math::
            \frac{\partial (\text{fugacity})_{g}}{\partial T} = P \left(\frac{1}
            {R T} \left(- T \frac{\partial}{\partial T} \operatorname{S_{dep}}
            {\left (T,P \right )} - \operatorname{S_{dep}}{\left (T,P \right )}
            + \frac{\partial}{\partial T} \operatorname{H_{dep}}{\left (T,P
            \right )}\right) - \frac{1}{R T^{2}} \left(- T \operatorname{
            S_{dep}}{\left (T,P \right )} + \operatorname{H_{dep}}{\left
            (T,P \right )}\right)\right) e^{\frac{1}{R T} \left(- T
            \operatorname{S_{dep}}{\left (T,P \right )} + \operatorname
            {H_{dep}}{\left (T,P \right )}\right)}
        '''
        T, P = self.T, self.P
        T_inv = 1.0/T
        S_dep_g = self.S_dep_g
        x4 = R_inv*(self.H_dep_g - T*S_dep_g)
        return P*(T_inv*R_inv*(self.dH_dep_dT_g - T*self.dS_dep_dT_g - S_dep_g)
                  - x4*T_inv*T_inv)*exp(T_inv*x4)

    @property
    def dfugacity_dP_l(self):
        r'''Derivative of fugacity with respect to pressure for the liquid
        phase, [-].

        .. math::
            \frac{\partial (\text{fugacity})_{l}}{\partial P} = \frac{P}{R T}
            \left(- T \frac{\partial}{\partial P} \operatorname{S_{dep}}{\left
            (T,P \right )} + \frac{\partial}{\partial P} \operatorname{H_{dep}}
            {\left (T,P \right )}\right) e^{\frac{1}{R T} \left(- T
            \operatorname{S_{dep}}{\left (T,P \right )} + \operatorname{
            H_{dep}}{\left (T,P \right )}\right)} + e^{\frac{1}{R T}
            \left(- T \operatorname{S_{dep}}{\left (T,P \right )}
            + \operatorname{H_{dep}}{\left (T,P \right )}\right)}
        '''
        T, P = self.T, self.P
        x0 = 1.0/(R*T)
        return (1.0 - P*x0*(T*self.dS_dep_dP_l - self.dH_dep_dP_l))*exp(
                -x0*(T*self.S_dep_l - self.H_dep_l))

    @property
    def dfugacity_dP_g(self):
        r'''Derivative of fugacity with respect to pressure for the gas
        phase, [-].

        .. math::
            \frac{\partial (\text{fugacity})_{g}}{\partial P} = \frac{P}{R T}
            \left(- T \frac{\partial}{\partial P} \operatorname{S_{dep}}{\left
            (T,P \right )} + \frac{\partial}{\partial P} \operatorname{H_{dep}}
            {\left (T,P \right )}\right) e^{\frac{1}{R T} \left(- T
            \operatorname{S_{dep}}{\left (T,P \right )} + \operatorname{
            H_{dep}}{\left (T,P \right )}\right)} + e^{\frac{1}{R T}
            \left(- T \operatorname{S_{dep}}{\left (T,P \right )}
            + \operatorname{H_{dep}}{\left (T,P \right )}\right)}
        '''
        T, P = self.T, self.P
        x0 = 1.0/(R*T)
        try:
            ans =  (1.0 - P*x0*(T*self.dS_dep_dP_g - self.dH_dep_dP_g))*exp(
                    -x0*(T*self.S_dep_g - self.H_dep_g))
            if isinf(ans) or isnan(ans):
                return 1.0
            return ans
        except Exception as e:
            if P < 1e-50:
                # Applies to gas phase only!
                return 1.0
            else:
                raise e

    @property
    def dphi_dT_l(self):
        r'''Derivative of fugacity coefficient with respect to temperature for
        the liquid phase, [1/K].

        .. math::
            \frac{\partial \phi}{\partial T} = \left(\frac{- T \frac{\partial}
            {\partial T} \operatorname{S_{dep}}{\left(T,P \right)}
            - \operatorname{S_{dep}}{\left(T,P \right)} + \frac{\partial}
            {\partial T} \operatorname{H_{dep}}{\left(T,P \right)}}{R T}
            - \frac{- T \operatorname{S_{dep}}{\left(T,P \right)}
            + \operatorname{H_{dep}}{\left(T,P \right)}}{R T^{2}}\right)
            e^{\frac{- T \operatorname{S_{dep}}{\left(T,P \right)}
            + \operatorname{H_{dep}}{\left(T,P \right)}}{R T}}
        '''
        T, P = self.T, self.P
        T_inv = 1.0/T
        x4 = T_inv*(T*self.S_dep_l - self.H_dep_l)
        return (-R_inv*T_inv*(T*self.dS_dep_dT_l + self.S_dep_l - x4
                             - self.dH_dep_dT_l)*exp(-R_inv*x4))

    @property
    def dphi_dT_g(self):
        r'''Derivative of fugacity coefficient with respect to temperature for
        the gas phase, [1/K].

        .. math::
            \frac{\partial \phi}{\partial T} = \left(\frac{- T \frac{\partial}
            {\partial T} \operatorname{S_{dep}}{\left(T,P \right)}
            - \operatorname{S_{dep}}{\left(T,P \right)} + \frac{\partial}
            {\partial T} \operatorname{H_{dep}}{\left(T,P \right)}}{R T}
            - \frac{- T \operatorname{S_{dep}}{\left(T,P \right)}
            + \operatorname{H_{dep}}{\left(T,P \right)}}{R T^{2}}\right)
            e^{\frac{- T \operatorname{S_{dep}}{\left(T,P \right)}
            + \operatorname{H_{dep}}{\left(T,P \right)}}{R T}}
        '''
        T, P = self.T, self.P
        T_inv = 1.0/T
        x4 = T_inv*(T*self.S_dep_g - self.H_dep_g)
        return (-R_inv*T_inv*(T*self.dS_dep_dT_g + self.S_dep_g - x4
                             - self.dH_dep_dT_g)*exp(-R_inv*x4))

    @property
    def dphi_dP_l(self):
        r'''Derivative of fugacity coefficient with respect to pressure for
        the liquid phase, [1/Pa].

        .. math::
            \frac{\partial \phi}{\partial P} = \frac{\left(- T \frac{\partial}
            {\partial P} \operatorname{S_{dep}}{\left(T,P \right)}
            + \frac{\partial}{\partial P} \operatorname{H_{dep}}{\left(T,P
            \right)}\right) e^{\frac{- T \operatorname{S_{dep}}{\left(T,P
            \right)} + \operatorname{H_{dep}}{\left(T,P \right)}}{R T}}}{R T}
        '''
        T = self.T
        x0 = self.S_dep_l
        x1 = self.H_dep_l
        x2 = 1.0/(R*T)
        return -x2*(T*self.dS_dep_dP_l - self.dH_dep_dP_l)*exp(-x2*(T*x0 - x1))

    @property
    def dphi_dP_g(self):
        r'''Derivative of fugacity coefficient with respect to pressure for
        the gas phase, [1/Pa].

        .. math::
            \frac{\partial \phi}{\partial P} = \frac{\left(- T \frac{\partial}
            {\partial P} \operatorname{S_{dep}}{\left(T,P \right)}
            + \frac{\partial}{\partial P} \operatorname{H_{dep}}{\left(T,P
            \right)}\right) e^{\frac{- T \operatorname{S_{dep}}{\left(T,P
            \right)} + \operatorname{H_{dep}}{\left(T,P \right)}}{R T}}}{R T}
        '''
        T = self.T
        x0 = self.S_dep_g
        x1 = self.H_dep_g
        x2 = 1.0/(R*T)
        return -x2*(T*self.dS_dep_dP_g - self.dH_dep_dP_g)*exp(-x2*(T*x0 - x1))

    @property
    def dbeta_dT_g(self):
        r'''Derivative of isobaric expansion coefficient with respect to
        temperature for the gas phase, [1/K^2].

        .. math::
            \frac{\partial \beta_g}{\partial T} = \frac{\frac{\partial^{2}}
            {\partial T^{2}} V{\left (T,P \right )_g}}{V{\left (T,P \right )_g}} -
            \frac{\left(\frac{\partial}{\partial T} V{\left (T,P \right )_g}
            \right)^{2}}{V^{2}{\left (T,P \right )_g}}
        '''
        V_inv = 1.0/self.V_g
        dV_dT = self.dV_dT_g
        return V_inv*(self.d2V_dT2_g - dV_dT*dV_dT*V_inv)

    @property
    def dbeta_dT_l(self):
        r'''Derivative of isobaric expansion coefficient with respect to
        temperature for the liquid phase, [1/K^2].

        .. math::
            \frac{\partial \beta_l}{\partial T} = \frac{\frac{\partial^{2}}
            {\partial T^{2}} V{\left (T,P \right )_l}}{V{\left (T,P \right )_l}} -
            \frac{\left(\frac{\partial}{\partial T} V{\left (T,P \right )_l}
            \right)^{2}}{V^{2}{\left (T,P \right )_l}}
        '''
        V_inv = 1.0/self.V_l
        dV_dT = self.dV_dT_l
        return V_inv*(self.d2V_dT2_l - dV_dT*dV_dT*V_inv)

    @property
    def dbeta_dP_g(self):
        r'''Derivative of isobaric expansion coefficient with respect to
        pressure for the gas phase, [1/(Pa*K)].

        .. math::
            \frac{\partial \beta_g}{\partial P} = \frac{\frac{\partial^{2}}
            {\partial T\partial P} V{\left (T,P \right )_g}}{V{\left (T,
            P \right )_g}} - \frac{\frac{\partial}{\partial P} V{\left (T,P
            \right )_g} \frac{\partial}{\partial T} V{\left (T,P \right )_g}}
            {V^{2}{\left (T,P \right )_g}}
        '''
        V_inv = 1.0/self.V_g
        dV_dT = self.dV_dT_g
        dV_dP = self.dV_dP_g
        return V_inv*(self.d2V_dTdP_g - dV_dT*dV_dP*V_inv)

    @property
    def dbeta_dP_l(self):
        r'''Derivative of isobaric expansion coefficient with respect to
        pressure for the liquid phase, [1/(Pa*K)].

        .. math::
            \frac{\partial \beta_g}{\partial P} = \frac{\frac{\partial^{2}}
            {\partial T\partial P} V{\left (T,P \right )_l}}{V{\left (T,
            P \right )_l}} - \frac{\frac{\partial}{\partial P} V{\left (T,P
            \right )_l} \frac{\partial}{\partial T} V{\left (T,P \right )_l}}
            {V^{2}{\left (T,P \right )_l}}
        '''
        V_inv = 1.0/self.V_l
        dV_dT = self.dV_dT_l
        dV_dP = self.dV_dP_l
        return V_inv*(self.d2V_dTdP_l - dV_dT*dV_dP*V_inv)

    @property
    def da_alpha_dP_g_V(self):
        r'''Derivative of the `a_alpha` with respect to
        pressure at constant volume (varying T) for the gas phase,
        [J^2/mol^2/Pa^2].

        .. math::
            \left(\frac{\partial a \alpha}{\partial P}\right)_{V}
            = \left(\frac{\partial a \alpha}{\partial T}\right)_{P}
            \cdot\left( \frac{\partial T}{\partial P}\right)_V
        '''
        return self.da_alpha_dT*self.dT_dP_g

    @property
    def da_alpha_dP_l_V(self):
        r'''Derivative of the `a_alpha` with respect to
        pressure at constant volume (varying T) for the liquid phase,
        [J^2/mol^2/Pa^2].

        .. math::
            \left(\frac{\partial a \alpha}{\partial P}\right)_{V}
            = \left(\frac{\partial a \alpha}{\partial T}\right)_{P}
            \cdot\left( \frac{\partial T}{\partial P}\right)_V
        '''
        return self.da_alpha_dT*self.dT_dP_l

    @property
    def d2a_alpha_dTdP_g_V(self):
        r'''Derivative of the temperature derivative of `a_alpha` with respect
        to pressure at constant volume (varying T) for the gas phase,
        [J^2/mol^2/Pa^2/K].

        .. math::
            \left(\frac{\partial \left(\frac{\partial a \alpha}{\partial T}
            \right)_P}{\partial P}\right)_{V}
            = \left(\frac{\partial^2 a \alpha}{\partial T^2}\right)_{P}
            \cdot\left( \frac{\partial T}{\partial P}\right)_V
            '''
        return self.d2a_alpha_dT2*self.dT_dP_g

    @property
    def d2a_alpha_dTdP_l_V(self):
        r'''Derivative of the temperature derivative of `a_alpha` with respect
        to pressure at constant volume (varying T) for the liquid phase,
        [J^2/mol^2/Pa^2/K].

        .. math::
            \left(\frac{\partial \left(\frac{\partial a \alpha}{\partial T}
            \right)_P}{\partial P}\right)_{V}
            = \left(\frac{\partial^2 a \alpha}{\partial T^2}\right)_{P}
            \cdot\left( \frac{\partial T}{\partial P}\right)_V
            '''
        return self.d2a_alpha_dT2*self.dT_dP_l

    @property
    def d2P_dVdP_g(self):
        r'''Second derivative of pressure with respect to molar volume and
        then pressure for the gas phase, [mol/m^3].

        .. math::
            \frac{\partial^2 P}{\partial V \partial P} =
            \frac{2 R T \frac{d}{d P} V{\left(P \right)}}{\left(- b + V{\left(P
            \right)}\right)^{3}} - \frac{\left(- \delta - 2 V{\left(P \right)}
            \right) \left(- 2 \delta \frac{d}{d P} V{\left(P \right)}
            - 4 V{\left(P \right)} \frac{d}{d P} V{\left(P \right)}\right)
            \operatorname{a\alpha}{\left(T \right)}}{\left(\delta V{\left(P
            \right)} + \epsilon + V^{2}{\left(P \right)}\right)^{3}} + \frac{2
            \operatorname{a\alpha}{\left(T \right)} \frac{d}{d P} V{\left(P
            \right)}}{\left(\delta V{\left(P \right)} + \epsilon + V^{2}
            {\left(P \right)}\right)^{2}}

        '''
        r'''Feels like a really strange derivative. Have not been able to construct
        it from others yet. Value is Symmetric - can calculate it both ways.
        Still feels like there should be a general method for obtaining these derivatives.

        from sympy import *
        P, T, R, b, delta, epsilon = symbols('P, T, R, b, delta, epsilon')
        a_alpha, V = symbols(r'a\alpha, V', cls=Function)

        dP_dV = 1/(1/(-R*T/(V(P) - b)**2 - a_alpha(T)*(-2*V(P) - delta)/(V(P)**2 + V(P)*delta + epsilon)**2))
        cse(diff(dP_dV, P), optimizations='basic')
        '''
        T, P, b, delta, epsilon = self.T, self.P, self.b, self.delta, self.epsilon
        x0 = self.V_g
        x1 = self.a_alpha
        x2 = delta*x0 + epsilon + x0*x0
        x50 = self.dV_dP_g
        x51 = x0 + x0 + delta
        x52 = 1.0/(b - x0)
        x2_inv = 1.0/x2
        return 2.0*(-R*T*x52*x52*x52 + x1*x2_inv*x2_inv*(1.0 - x51*x51*x2_inv))*x50

    @property
    def d2P_dVdP_l(self):
        r'''Second derivative of pressure with respect to molar volume and
        then pressure for the liquid phase, [mol/m^3].

        .. math::
            \frac{\partial^2 P}{\partial V \partial P} =
            \frac{2 R T \frac{d}{d P} V{\left(P \right)}}{\left(- b + V{\left(P
            \right)}\right)^{3}} - \frac{\left(- \delta - 2 V{\left(P \right)}
            \right) \left(- 2 \delta \frac{d}{d P} V{\left(P \right)}
            - 4 V{\left(P \right)} \frac{d}{d P} V{\left(P \right)}\right)
            \operatorname{a\alpha}{\left(T \right)}}{\left(\delta V{\left(P
            \right)} + \epsilon + V^{2}{\left(P \right)}\right)^{3}} + \frac{2
            \operatorname{a\alpha}{\left(T \right)} \frac{d}{d P} V{\left(P
            \right)}}{\left(\delta V{\left(P \right)} + \epsilon + V^{2}
            {\left(P \right)}\right)^{2}}

        '''
        T, b, delta, epsilon = self.T, self.b, self.delta, self.epsilon
        x0 = self.V_l
        x1 = self.a_alpha
        x2 = delta*x0 + epsilon + x0*x0
        x50 = self.dV_dP_l
        x51 = x0 + x0 + delta
        x52 = 1.0/(b - x0)
        x2_inv = 1.0/x2
        return 2.0*(-R*T*x52*x52*x52 + x1*x2_inv*x2_inv*(1.0 - x51*x51*x2_inv))*x50

    @property
    def d2P_dVdT_TP_g(self):
        r'''Second derivative of pressure with respect to molar volume and
        then temperature at constant temperature then pressure for the gas
        phase, [Pa*mol/m^3/K].

        .. math::
            \left(\frac{\partial^2 P}{\partial V \partial T}\right)_{T,P} =
            \frac{2 R T \frac{d}{d T} V{\left(T \right)}}{\left(- b + V{\left(T
            \right)}\right)^{3}} - \frac{R}{\left(- b + V{\left(T \right)}
            \right)^{2}} - \frac{\left(- \delta - 2 V{\left(T \right)}\right)
            \left(- 2 \delta \frac{d}{d T} V{\left(T \right)} - 4 V{\left(T
            \right)} \frac{d}{d T} V{\left(T \right)}\right) \operatorname{
            a\alpha}{\left(T \right)}}{\left(\delta V{\left(T \right)}
            + \epsilon + V^{2}{\left(T \right)}\right)^{3}} - \frac{\left(
            - \delta - 2 V{\left(T \right)}\right) \frac{d}{d T} \operatorname{
            a\alpha}{\left(T \right)}}{\left(\delta V{\left(T \right)}
            + \epsilon + V^{2}{\left(T \right)}\right)^{2}} + \frac{2
            \operatorname{a\alpha}{\left(T \right)} \frac{d}{d T} V{\left(T
            \right)}}{\left(\delta V{\left(T \right)} + \epsilon + V^{2}{\left(
            T \right)}\right)^{2}}
        '''
        T, b, delta, epsilon = self.T, self.b, self.delta, self.epsilon
        x0 = self.V_g
        x2 = 2.0*self.dV_dT_g
        x1 = self.b - x0
        x1_inv = 1.0/x1
        x3 = delta*x0 + epsilon + x0*x0
        x3_inv = 1.0/x3
        x4 = x3_inv*x3_inv
        x5 = self.a_alpha
        x6 = x2*x5
        x7 = delta + x0 + x0
        return (-x1_inv*x1_inv*R*(T*x2*x1_inv + 1.0) + x4*x6
                + x4*x7*(self.da_alpha_dT - x6*x7*x3_inv))

    @property
    def d2P_dVdT_TP_l(self):
        r'''Second derivative of pressure with respect to molar volume and
        then temperature at constant temperature then pressure for the liquid
        phase, [Pa*mol/m^3/K].

        .. math::
            \left(\frac{\partial^2 P}{\partial V \partial T}\right)_{T,P} =
            \frac{2 R T \frac{d}{d T} V{\left(T \right)}}{\left(- b + V{\left(T
            \right)}\right)^{3}} - \frac{R}{\left(- b + V{\left(T \right)}
            \right)^{2}} - \frac{\left(- \delta - 2 V{\left(T \right)}\right)
            \left(- 2 \delta \frac{d}{d T} V{\left(T \right)} - 4 V{\left(T
            \right)} \frac{d}{d T} V{\left(T \right)}\right) \operatorname{
            a\alpha}{\left(T \right)}}{\left(\delta V{\left(T \right)}
            + \epsilon + V^{2}{\left(T \right)}\right)^{3}} - \frac{\left(
            - \delta - 2 V{\left(T \right)}\right) \frac{d}{d T} \operatorname{
            a\alpha}{\left(T \right)}}{\left(\delta V{\left(T \right)}
            + \epsilon + V^{2}{\left(T \right)}\right)^{2}} + \frac{2
            \operatorname{a\alpha}{\left(T \right)} \frac{d}{d T} V{\left(T
            \right)}}{\left(\delta V{\left(T \right)} + \epsilon + V^{2}{\left(
            T \right)}\right)^{2}}
        '''
        T, b, delta, epsilon = self.T, self.b, self.delta, self.epsilon
        x0 = self.V_l
        x2 = 2.0*self.dV_dT_l
        x1 = self.b - x0
        x1_inv = 1.0/x1
        x3 = delta*x0 + epsilon + x0*x0
        x3_inv = 1.0/x3
        x4 = x3_inv*x3_inv
        x5 = self.a_alpha
        x6 = x2*x5
        x7 = delta + x0 + x0
        return (-x1_inv*x1_inv*R*(T*x2*x1_inv + 1.0) + x4*x6
                + x4*x7*(self.da_alpha_dT - x6*x7*x3_inv))

    @property
    def d2P_dT2_PV_g(self):
        r'''Second derivative of pressure with respect to temperature twice,
        but with pressure held constant the first time and volume held
        constant the second time for the gas phase, [Pa/K^2].

        .. math::
            \left(\frac{\partial^2 P}{\partial T \partial T}\right)_{P,V} =
            - \frac{R \frac{d}{d T} V{\left(T \right)}}{\left(- b + V{\left(T
            \right)}\right)^{2}} - \frac{\left(- \delta \frac{d}{d T} V{\left(T
            \right)} - 2 V{\left(T \right)} \frac{d}{d T} V{\left(T \right)}
            \right) \frac{d}{d T} \operatorname{a\alpha}{\left(T \right)}}
            {\left(\delta V{\left(T \right)} + \epsilon + V^{2}{\left(T
            \right)}\right)^{2}} - \frac{\frac{d^{2}}{d T^{2}}
            \operatorname{a\alpha}{\left(T \right)}}{\delta V{\left(T \right)}
            + \epsilon + V^{2}{\left(T \right)}}
        '''
        T, b, delta, epsilon = self.T, self.b, self.delta, self.epsilon
        V = self.V_g
        dV_dT = self.dV_dT_g

        x2 = self.a_alpha
        x0 = V
        x1 = dV_dT
        x3 = delta*x0 + epsilon + x0*x0
        x3_inv = 1.0/x3
        x50 = 1.0/(b - x0)
        return (-R*x1*x50*x50 + x1*(delta + x0 + x0)*self.da_alpha_dT*x3_inv*x3_inv - self.d2a_alpha_dT2*x3_inv)

    @property
    def d2P_dT2_PV_l(self):
        r'''Second derivative of pressure with respect to temperature twice,
        but with pressure held constant the first time and volume held
        constant the second time for the liquid phase, [Pa/K^2].

        .. math::
            \left(\frac{\partial^2 P}{\partial T \partial T}\right)_{P,V} =
            - \frac{R \frac{d}{d T} V{\left(T \right)}}{\left(- b + V{\left(T
            \right)}\right)^{2}} - \frac{\left(- \delta \frac{d}{d T} V{\left(T
            \right)} - 2 V{\left(T \right)} \frac{d}{d T} V{\left(T \right)}
            \right) \frac{d}{d T} \operatorname{a\alpha}{\left(T \right)}}
            {\left(\delta V{\left(T \right)} + \epsilon + V^{2}{\left(T
            \right)}\right)^{2}} - \frac{\frac{d^{2}}{d T^{2}}
            \operatorname{a\alpha}{\left(T \right)}}{\delta V{\left(T \right)}
            + \epsilon + V^{2}{\left(T \right)}}
        '''
        T, b, delta, epsilon = self.T, self.b, self.delta, self.epsilon
        V = self.V_l
        dV_dT = self.dV_dT_l

        x0 = V
        x1 = dV_dT
        x2 = self.a_alpha
        x3 = delta*x0 + epsilon + x0*x0
        x3_inv = 1.0/x3
        x50 = 1.0/(b - x0)
        return (-R*x1*x50*x50 + x1*(delta + x0 + x0)*self.da_alpha_dT*x3_inv*x3_inv - self.d2a_alpha_dT2*x3_inv)

    @property
    def d2P_dTdP_g(self):
        r'''Second derivative of pressure with respect to temperature and,
        then pressure; and with volume held constant at first, then temperature,
        for the gas phase, [1/K].

        .. math::
            \left(\frac{\partial^2 P}{\partial T \partial P}\right)_{V, T} =
            - \frac{R \frac{d}{d P} V{\left(P \right)}}{\left(- b + V{\left(P
            \right)}\right)^{2}} - \frac{\left(- \delta \frac{d}{d P} V{\left(P
            \right)} - 2 V{\left(P \right)} \frac{d}{d P} V{\left(P \right)}
            \right) \frac{d}{d T} \operatorname{a\alpha}{\left(T \right)}}
            {\left(\delta V{\left(P \right)} + \epsilon + V^{2}{\left(P
            \right)}\right)^{2}}
        '''
        V = self.V_g
        dV_dP = self.dV_dP_g
        T, b, delta, epsilon = self.T, self.b, self.delta, self.epsilon
        da_alpha_dT = self.da_alpha_dT
        x0 = V - b
        x1 = delta*V + epsilon + V*V
        return (-R*dV_dP/(x0*x0) - (-delta*dV_dP - 2.0*V*dV_dP)*da_alpha_dT/(x1*x1))


    @property
    def d2P_dTdP_l(self):
        r'''Second derivative of pressure with respect to temperature and,
        then pressure; and with volume held constant at first, then temperature,
        for the liquid phase, [1/K].

        .. math::
            \left(\frac{\partial^2 P}{\partial T \partial P}\right)_{V, T} =
            - \frac{R \frac{d}{d P} V{\left(P \right)}}{\left(- b + V{\left(P
            \right)}\right)^{2}} - \frac{\left(- \delta \frac{d}{d P} V{\left(P
            \right)} - 2 V{\left(P \right)} \frac{d}{d P} V{\left(P \right)}
            \right) \frac{d}{d T} \operatorname{a\alpha}{\left(T \right)}}
            {\left(\delta V{\left(P \right)} + \epsilon + V^{2}{\left(P
            \right)}\right)^{2}}
        '''
        V = self.V_l
        dV_dP = self.dV_dP_l
        T, b, delta, epsilon = self.T, self.b, self.delta, self.epsilon
        da_alpha_dT = self.da_alpha_dT
        x0 = V - b
        x1 = delta*V + epsilon + V*V
        return (-R*dV_dP/(x0*x0) - (-delta*dV_dP - 2.0*V*dV_dP)*da_alpha_dT/(x1*x1))

    @property
    def lnphi_l(self):
        r'''The natural logarithm of the fugacity coefficient for
        the liquid phase, [-].
        '''
        return self.G_dep_l*R_inv/self.T

    @property
    def lnphi_g(self):
        r'''The natural logarithm of the fugacity coefficient for
        the gas phase, [-].
        '''
        return log(self.phi_g)



class PR(GCEOS):
    r'''Class for solving the Peng-Robinson [1]_ [2]_ cubic
    equation of state for a pure compound. Subclasses :obj:`GCEOS`, which
    provides the methods for solving the EOS and calculating its assorted
    relevant thermodynamic properties. Solves the EOS on initialization.

    The main methods here are :obj:`PR.a_alpha_and_derivatives_pure`, which calculates
    :math:`a \alpha` and its first and second derivatives, and :obj:`PR.solve_T`, which from a
    specified `P` and `V` obtains `T`.

    Two of (`T`, `P`, `V`) are needed to solve the EOS.

    .. math::
        P = \frac{RT}{v-b}-\frac{a\alpha(T)}{v(v+b)+b(v-b)}

    .. math::
        a=0.45724\frac{R^2T_c^2}{P_c}

    .. math::
	     b=0.07780\frac{RT_c}{P_c}

    .. math::
        \alpha(T)=[1+\kappa(1-\sqrt{T_r})]^2

    .. math::
        \kappa=0.37464+1.54226\omega-0.26992\omega^2

    Parameters
    ----------
    Tc : float
        Critical temperature, [K]
    Pc : float
        Critical pressure, [Pa]
    omega : float
        Acentric factor, [-]
    T : float, optional
        Temperature, [K]
    P : float, optional
        Pressure, [Pa]
    V : float, optional
        Molar volume, [m^3/mol]

    Examples
    --------
    T-P initialization, and exploring each phase's properties:

    >>> eos = PR(Tc=507.6, Pc=3025000.0, omega=0.2975, T=400., P=1E6)
    >>> eos.V_l, eos.V_g
    (0.000156073184785, 0.0021418768167)
    >>> eos.phase
    'l/g'
    >>> eos.H_dep_l, eos.H_dep_g
    (-26111.8775716, -3549.30057795)
    >>> eos.S_dep_l, eos.S_dep_g
    (-58.098447843, -6.4394518931)
    >>> eos.U_dep_l, eos.U_dep_g
    (-22942.1657091, -2365.3923474)
    >>> eos.G_dep_l, eos.G_dep_g
    (-2872.49843435, -973.51982071)
    >>> eos.A_dep_l, eos.A_dep_g
    (297.21342811, 210.38840980)
    >>> eos.beta_l, eos.beta_g
    (0.00269337091778, 0.0101232239111)
    >>> eos.kappa_l, eos.kappa_g
    (9.3357215438e-09, 1.97106698097e-06)
    >>> eos.Cp_minus_Cv_l, eos.Cp_minus_Cv_g
    (48.510162249, 44.544161128)
    >>> eos.Cv_dep_l, eos.Cp_dep_l
    (18.8921126734, 59.0878123050)

    P-T initialization, liquid phase, and round robin trip:

    >>> eos = PR(Tc=507.6, Pc=3025000, omega=0.2975, T=299., P=1E6)
    >>> eos.phase, eos.V_l, eos.H_dep_l, eos.S_dep_l
    ('l', 0.000130222125139, -31134.75084, -72.47561931)

    T-V initialization, liquid phase:

    >>> eos2 = PR(Tc=507.6, Pc=3025000, omega=0.2975, T=299., V=eos.V_l)
    >>> eos2.P, eos2.phase
    (1000000.00, 'l')

    P-V initialization at same state:

    >>> eos3 = PR(Tc=507.6, Pc=3025000, omega=0.2975, V=eos.V_l, P=1E6)
    >>> eos3.T, eos3.phase
    (299.0000000000, 'l')

    Notes
    -----
    The constants in the expresions for `a` and `b` are given to full precision
    in the actual code, as derived in [3]_.

    The full expression for critical compressibility is:

    .. math::
        Z_c = \frac{1}{32} \left(\sqrt[3]{16 \sqrt{2}-13}-\frac{7}{\sqrt[3]
        {16 \sqrt{2}-13}}+11\right)

    References
    ----------
    .. [1] Peng, Ding-Yu, and Donald B. Robinson. "A New Two-Constant Equation
       of State." Industrial & Engineering Chemistry Fundamentals 15, no. 1
       (February 1, 1976): 59-64. doi:10.1021/i160057a011.
    .. [2] Robinson, Donald B., Ding-Yu Peng, and Samuel Y-K Chung. "The
       Development of the Peng - Robinson Equation and Its Application to Phase
       Equilibrium in a System Containing Methanol." Fluid Phase Equilibria 24,
       no. 1 (January 1, 1985): 25-41. doi:10.1016/0378-3812(85)87035-7.
    .. [3] Privat, R., and J.-N. Jaubert. "PPR78, a Thermodynamic Model for the
       Prediction of Petroleum Fluid-Phase Behaviour," 11. EDP Sciences, 2011.
       doi:10.1051/jeep/201100011.
    '''
    # constant part of `a`,
    # X = (-1 + (6*sqrt(2)+8)**Rational(1,3) - (6*sqrt(2)-8)**Rational(1,3))/3
    # (8*(5*X+1)/(49-37*X)).evalf(40)
    c1 = 0.4572355289213821893834601962251837888504
    '''Full value of the constant in the `a` parameter'''
    c1R2 = c1*R2

    # Constant part of `b`, (X/(X+3)).evalf(40)
    c2 = 0.0777960739038884559718447100373331839711
    '''Full value of the constant in the `b` parameter'''
    c2R = c2*R
    c1R2_c2R = c1R2/c2R
    #    c1, c2 = 0.45724, 0.07780

    # Zc is the mechanical compressibility for mixtures as well.
    Zc = 0.3074013086987038480093850966542222720096
    '''Mechanical compressibility of Peng-Robinson EOS'''

    Psat_coeffs_limiting = [-3.4758880164801873, 0.7675486448347723]

    Psat_coeffs_critical = [13.906174756604267, -8.978515559640332,
                            6.191494729386664, -3.3553014047359286,
                            1.0000000000011509]

    Psat_cheb_coeffs = [-7.693430141477579, -7.792157693145173, -0.12584439451814622, 0.0045868660863990305,
                        0.011902728116315585, -0.00809984848593371, 0.0035807374586641324, -0.001285457896498948,
                        0.0004379441379448949, -0.0001701325511665626, 7.889450459420399e-05, -3.842330780886875e-05,
                        1.7884847876342805e-05, -7.9432179091441e-06, 3.51726370898656e-06, -1.6108797741557683e-06,
                        7.625638345550717e-07, -3.6453554523813245e-07, 1.732454904858089e-07, -8.195124459058523e-08,
                        3.8929380082904216e-08, -1.8668536344161905e-08, 9.021955971552252e-09, -4.374277331168795e-09,
                        2.122697092724708e-09, -1.0315557015083254e-09, 5.027805333255708e-10, -2.4590905784642285e-10,
                        1.206301486380689e-10, -5.932583414867791e-11, 2.9274476912683964e-11, -1.4591650777202522e-11,
                        7.533835507484918e-12, -4.377200831613345e-12, 1.7413208326438542e-12]
    # below  - down to .14 Tr
#    Psat_cheb_coeffs = [-69.78144560030312, -70.82020621910401, -0.5505993362058134, 0.262763240774557, -0.13586962327984622, 0.07091484524874882, -0.03531507189835045, 0.015348266653126313, -0.004290800414097142, -0.0015192254949775404, 0.004230003950690049, -0.005148646330256051, 0.005067979846360524, -0.004463618393006094, 0.0036338412594165456, -0.002781745442601943, 0.0020410583004693912, -0.0014675469823800154, 0.001041797382518202, -0.0007085008245359792, 0.0004341450533632967, -0.00023059133991796472, 0.00012404966848973944, -0.00010575986390189084, 0.00011927874294723816, -0.00010216011382070127, 4.142986825089964e-05, 1.6994654942134455e-05, -2.0393896226146606e-05, -3.05495184394464e-05, 7.840494892004187e-05, -6.715144915784917e-05, 1.9360256298218764e-06, 5.342823303794287e-05, -4.2445268102696054e-05, -2.258059184830652e-05, 7.156133295478447e-05, -5.0419963297068014e-05, -2.1185333936025785e-05, 6.945722167248469e-05, -4.3468774802286496e-05, -3.0211658906858938e-05, 7.396450066832002e-05, -4.0987041756199036e-05, -3.4507186813052766e-05, 3.6619358939125855e-05]
    # down to .05 Tr
#    Psat_cheb_coeffs = [-71.62442148475718, -72.67946752713178, -0.5550432977559888, 0.2662527679044299, -0.13858385912471755, 0.07300013042829502, -0.03688566755461173, 0.01648745160444604, -0.005061858504315144, -0.0010519595693067093, 0.0039868988560367085, -0.005045456840770146, 0.00504419254495023, -0.0044982000664379905, 0.003727506855649437, -0.002922838794275898, 0.0021888012528213734, -0.0015735578492615076, 0.0010897606359061226, -0.0007293553555925913, 0.0004738606767778966, -0.00030120118607927907, 0.00018992197213856394, -0.00012147385378832608, 8.113736696036817e-05, -5.806550163389163e-05, 4.4822397778703055e-05, -3.669084579413651e-05, 3.0945466319478186e-05, -2.62003968013127e-05, 2.1885122184587654e-05, -1.786717828032663e-05, 1.420082721312861e-05, -1.0981475209780111e-05, 8.276527284992199e-06, -6.100440122314813e-06, 4.420342273408809e-06, -3.171239452318529e-06, 2.2718591475182304e-06, -1.641149583754854e-06, 1.2061284404980935e-06, -9.067266070702959e-07, 6.985214276328142e-07, -5.490755862981909e-07, 4.372991567070929e-07, -3.504743494298746e-07, 2.8019662848682576e-07, -2.2266768846404626e-07, 1.7533403880408145e-07, -1.3630227589226426e-07, 1.0510214144142285e-07, -8.02098792008235e-08, 6.073935683412093e-08, -4.6105511380996746e-08, 3.478599121821662e-08, -2.648029023793574e-08, 2.041302301328165e-08, -1.5671212844805128e-08, 1.2440282394539782e-08, -9.871977759603047e-09, 7.912503992331811e-09, -6.6888910721434e-09, 5.534654087073205e-09, -4.92019981055108e-09, 4.589363968756223e-09, -2.151778718334702e-09]
    # down to .05 Tr polishing
#    Psat_cheb_coeffs = [-73.9119088855554, -74.98674794418481, -0.5603678572345178, 0.2704608002227193, -0.1418754021264281, 0.07553218818095526, -0.03878657980070652, 0.017866520164384912, -0.0060152224341743525, -0.0004382750653244775, 0.003635841462596336, -0.004888955750612924, 0.005023631814771542, -0.004564880757514128, 0.003842769402817585, -0.0030577040987875793, 0.0023231191552369407, -0.001694755295849508, 0.0011913577693282759, -0.0008093955530850967, 0.0005334402485338361, -0.0003431831424850387, 0.00021792836239828482, -0.00013916167527852, 9.174638441139245e-05, -6.419699908390207e-05, 4.838277855408256e-05, -3.895686370452493e-05, 3.267491660000825e-05, -2.7780478658642705e-05, 2.3455257030895833e-05, -1.943068869205973e-05, 1.5702249378726904e-05, -1.2352834841441616e-05, 9.468188716352547e-06, -7.086815965689662e-06, 5.202794456673999e-06, -3.7660662091643354e-06, 2.710802447723022e-06, -1.9547001517481854e-06, 1.4269579917305496e-06, -1.0627333211922062e-06, 8.086972219940435e-07, -6.313736088052035e-07, 5.002098614800398e-07, -4.014517222719182e-07, 3.222357369727768e-07, -2.591706410738203e-07, 2.0546606649125658e-07, -1.6215902481453263e-07, 1.2645321295092458e-07, -9.678506993483597e-08, 7.52490799383037e-08, -5.60685972986457e-08, 4.3358661542007224e-08, -3.2329350971261814e-08, 2.5091238603112617e-08, -1.8903964302567286e-08, 1.4892047699817043e-08, -1.1705624527623068e-08, 8.603302527636011e-09, -7.628847828412486e-09, 5.0543164590698825e-09, -5.102159698856454e-09, 3.0709992836479988e-09, -2.972533529000884e-09, 2.0494601230946347e-09, -1.626141536313283e-09, 1.6617716853181003e-09, -6.470653307871083e-10, 1.1333690091031717e-09, -1.2451614782651999e-10, 1.098942683163892e-09, 9.673645066411718e-11, 6.206934530152836e-10, -1.1913910201270805e-10, 3.559906774745769e-11, -5.419942764994107e-10, -2.372580701782284e-10, -5.785415972247437e-10, -1.789757696430208e-10]
    # down to .05 with lots of failures C40 only
#    Psat_cheb_coeffs =  [-186.30264784196294, -188.01235085131194, -0.6975588305160902, 0.38422679790906106, -0.2358303051434559, 0.15258449381119304, -0.101338177792044, 0.0679573457611134, -0.045425247476661136, 0.029879338234709937, -0.019024330378443737, 0.011418999154577504, -0.006113230472632388, 0.00246054797767154, -4.3960533109688155e-06, -0.0015825897164979809, 0.002540504992834563, -0.003046881596822211, 0.0032353807402903272, -0.0032061955400497044, 0.0030337264005811464, -0.0027744314554593126, 0.002469806934918433, -0.002149376765619085, 0.001833408492489406, -0.00153552022142691, 0.0012645817528752557, -0.0010249792000921317, 0.0008181632585418055, -0.0006436998283177283, 0.0004995903113614604, -0.0003828408287994695, 0.0002896812774307662, -0.00021674416012176133, 0.00016131784370737042, -0.00012009195488808489, 8.966908457382076e-05, -6.764450681363164e-05, 5.209192773849304e-05, -4.1139971086693995e-05, 3.3476318185800505e-05, -2.8412997762476805e-05, 2.513421113263226e-05, -2.2567508719078435e-05, 2.0188809493379843e-05, -1.810962700274516e-05, 1.643508229137845e-05, -1.503569055933669e-05, 1.3622272823701577e-05, -1.2076671646564277e-05, 1.054271875585668e-05, -9.007273271254411e-06, 7.523720857264602e-06, -6.424404525130439e-06, 5.652203861001342e-06, -4.7755499168431625e-06, 3.7604252783225858e-06, -2.92395389072605e-06, 2.3520802660480336e-06, -1.9209673206999083e-06, 1.6125790706312328e-06, -1.4083468032508143e-06, 1.1777450938630518e-06, -8.636616122606049e-07, 5.749905340593687e-07, -4.644992178826096e-07, 5.109912172256424e-07, -5.285927442208997e-07, 4.4610491153173465e-07, -3.3435155715273366e-07, 2.2022096388817243e-07, -1.3138808837994352e-07, 1.5788807254228123e-07, -2.6570415873228444e-07, 2.820563887584985e-07, -1.6783703722562406e-07, 4.477559158897425e-08, -2.4698813388799755e-09, 5.082691394016857e-08, -1.364026020206371e-07, 1.6850593650100272e-07, -1.0443374638586546e-07, -6.029473813268628e-10, 5.105380858617091e-08, -1.5066843023282578e-08, -5.630921379297198e-08, 9.561766786891034e-08, -8.044216329068123e-08, 3.359993333902796e-08, 1.692366968619578e-08, -2.021364343358841e-08]
     # down to .03, plenty of failures
#    Psat_cheb_coeffs = [-188.50329975567104, -190.22994960376462, -0.6992886012204886, 0.3856961269737735, -0.23707446208582353, 0.15363415372584763, -0.10221883018831106, 0.06869084576669, -0.046030774233320346, 0.03037297246598552, -0.019421744608583133, 0.011732910491046633, -0.006355800820106353, 0.0026413894471214202, -0.0001333621829559692, -0.0014967435287118152, 0.002489721202961943, -0.00302447283347462, 0.0032350727289014642, -0.0032223921492743357, 0.0030622558268892, -0.0028113049747675455, 0.002511348612059362, -0.002192644454555338, 0.0018764599744331163, -0.0015770771123065552, 0.0013034116032509804, -0.0010603100672178776, 0.00084960767850329, -0.0006709816561447436, 0.0005226330473731801, -0.0004018349441941878, 0.0003053468509191052, -0.00022974201509485604, 0.00017163053097478257, -0.0001278303586505278, 9.545950876002835e-05, -7.200007894259846e-05, 5.5312909934416405e-05, -4.3632781581719854e-05, 3.554641644507928e-05, -2.99488097950353e-05, 2.6011962388807256e-05, -2.3127603908643427e-05, 2.0875472981740965e-05, -1.8975408339047864e-05, 1.7255291079923385e-05, -1.562250114123633e-05, 1.4033483268247027e-05, -1.2483202707948607e-05, 1.0981181475278024e-05, -9.547990214685254e-06, 8.20534723265339e-06, -6.970215811404035e-06, 5.857096216944197e-06, -4.8714713996210945e-06, 4.015088107327757e-06, -3.2837642912761844e-06, 2.6688332761922373e-06, -2.1605704853781956e-06, 1.745415965345872e-06, -1.4112782858614675e-06, 1.1450344603347899e-06, -9.34468189749192e-07, 7.693687927218034e-07, -6.395653830685742e-07, 5.378418354520407e-07, -4.570688107726579e-07, 3.922470141699613e-07, -3.396066879296283e-07, 2.9547505651179775e-07, -2.5824629138078686e-07, 2.259435099158857e-07, -1.9759059073588738e-07, 1.7245665023281603e-07, -1.499107122703144e-07, 1.2993920706246258e-07, -1.1188458371271578e-07, 9.59786582193289e-08, -8.193904465038978e-08, 6.951736088200208e-08, -5.883242593822998e-08, 4.953479013200448e-08, -4.159778119910192e-08, 3.4903544554923914e-08, -2.9199660726126307e-08, 2.4491065764276586e-08, -2.0543807377807442e-08, 1.716620639244989e-08, -1.4598093803545008e-08, 1.2247184453541803e-08, -1.0378062685590349e-08, 8.941636289359033e-09, -7.547512972569913e-09, 6.5406029883590885e-09, -5.55017639345453e-09, 4.857924129262302e-09, -4.170327848134446e-09, 3.5473818590708514e-09, -3.1820101162273115e-09, 2.634813506155291e-09, -2.3186710334946806e-09, 1.9854991410760484e-09, -1.698026932061246e-09, 1.4939355398374196e-09, -1.2257013267845049e-09, 1.1034926144506615e-09, -8.867213325365261e-10, 7.759313594207437e-10, -6.85530513757325e-10, 5.315937675947832e-10, -5.001264119638624e-10, 4.2230130059116994e-10, -3.259379961024697e-10, 2.8696408042785254e-10, -2.654348289559891e-10, 2.240260857681517e-10, -1.5881755448515084e-10, 1.7089871651079086e-10, -1.743032336304004e-10, 5.736029218880029e-11, -9.974594793790009e-11, 1.2854164813721342e-10, -5.569999528883679e-11, 5.432760350528726e-11, -5.900487596351839e-11, 7.348655484042815e-11, 1.9834070367000245e-12, 3.887800704201888e-11, -6.528210426664377e-11, 6.144420801150463e-12, -2.0697350409069892e-11, 9.512216860539657e-12, -4.439607915237426e-11, -1.6185927706642567e-11, -2.8071628138323645e-12, 6.158579755107668e-11, 2.148407244207534e-11, 5.277970985609337e-13, -9.859059640730805e-12, 4.1564767036192385e-12, -1.5577673049063656e-11, -1.2654069415571345e-12, -1.9761710714008562e-12, 9.40276686806768e-12, 4.583732482119074e-13, -1.8523582732792032e-11, -1.7428972653131536e-11, 2.334371921024897e-11, 1.2661569384099514e-11, -2.4431492094169338e-11, -2.720598171659233e-11, 1.579179961710281e-11, 4.682966091729829e-11, 2.026395923889618e-11, -4.163510324266956e-11, -2.7091399111035808e-11, 3.978859743850732e-11, 3.993365393136633e-11, -2.4706365750991333e-11, -2.8201589338545247e-11]
#    Psat_cheb_coeffs =  [-188.81248459710693, -190.53226813843213, -0.6992718797266877, 0.3857083557782601, -0.23710917890714395, 0.15368561772753983, -0.10228211161653594, 0.06876166878498034, -0.046105558737181966, 0.030448740221432544, -0.019496099441454324, 0.01180400058944964, -0.006422229275450882, 0.002702227307086234, -0.00018800410519084597, -0.0014485238631714243, 0.0024479474900583895, -0.002988894024752606, 0.0032053382330997785, -0.003197984048551589, 0.0030426262430619812, -0.0027958384579597137, 0.0024994432437511482, -0.00218371114178375, 0.0018699437151919942, -0.0015724843629802854, 0.0013002928376298992, -0.0010582955457831876, 0.0008483768179051751, -0.0006702845742590901, 0.0005222702922150421, -0.0004016564112164708, 0.0003052504825598366, -0.00022965330503168022, 0.00017151209256412164, -0.00012765639237664444, 9.522751362437718e-05, -7.17145087909031e-05, 5.498576051758942e-05, -4.328024825801364e-05, 3.518008638334846e-05, -2.9585552080573432e-05, 2.5660899927246663e-05, -2.2801213593209296e-05, 2.0579135430209277e-05, -1.871227629774825e-05, 1.702697381072197e-05, -1.5427107330232484e-05, 1.3871955438611369e-05, -1.235063269577285e-05, 1.087503047126396e-05, -9.463372111120008e-06, 8.138409928400627e-06, -6.918751587310431e-06, 5.817036690746729e-06, -4.841268302762132e-06, 3.990762592248579e-06, -3.264055878954419e-06, 2.6526744772618845e-06, -2.146826614278467e-06, 1.7339220505229884e-06, -1.4002686597492801e-06, 1.1352817872143799e-06, -9.252727697582733e-07, 7.610055457905131e-07, -6.319237506120556e-07, 5.30160897737689e-07, -4.5034836164150563e-07, 3.8588236023116243e-07, -3.345288398991865e-07, 2.910099599025734e-07, -2.538502269447694e-07, 2.2221275929649412e-07, -1.9404386102611735e-07, 1.7012903413041972e-07, -1.4791267614537682e-07, 1.281131161442957e-07, -1.1035351009983888e-07, 9.412216917920838e-08, -8.103521480312085e-08, 6.889862034626618e-08, -5.823229805384481e-08, 4.888865274151847e-08, -4.0647361572055817e-08, 3.461181492625629e-08, -2.890818104595808e-08, 2.4189127295759093e-08, -2.036506388954876e-08, 1.6621054692260028e-08, -1.4376599744841544e-08, 1.2262293144383739e-08, -1.0166543599991339e-08, 8.776172074614484e-09, -7.244748882363349e-09, 6.552057774765062e-09, -5.655401910624057e-09, 4.4124427509814644e-09, -4.138406545361605e-09, 3.4155934985322144e-09, -3.1467981765942498e-09, 3.138041596064127e-09, -2.097881746535653e-09, 1.6538597491971884e-09, -1.4302796654967797e-09, 1.3958696624380472e-09, -1.6941697510614072e-09, 1.1559050790778446e-09, -8.424336557798272e-10, 7.445069759938515e-10, -3.8008350586066653e-10, 6.681447868524303e-10, -5.609484209193093e-10, 1.1709177677205352e-10, -5.781259004102078e-10, 5.45265361901197e-10, -1.3987335287680026e-10, 1.7128157135074418e-10, 1.0377866018526204e-10, 1.449451573983006e-10, -4.977625195297418e-10, 1.7368603686632612e-10, -3.571321706516851e-11, -1.6249813391308165e-10, 4.6148221569532015e-11, 3.9554757121876716e-10, -1.0268016727946628e-10, -7.436027752479989e-11, -1.6876374859490107e-10, -4.24547853876368e-11, 9.538626006134858e-12, 1.5150070863903953e-10, 2.7005277922459003e-10, -1.6342760518896042e-11, -4.572503911555491e-10, 4.922727672815753e-11, 9.160300994028991e-11, -7.120976338703244e-11, 2.164872706420613e-10, 1.1646536920908047e-10, -2.7132159904485077e-10, -9.18445653054099e-11, 1.1410414945528784e-10, 1.1967624164073171e-10, -5.5743966043066313e-11, 3.9042323803713426e-11, 4.316392256370049e-11, -1.8428367625021157e-10, -9.040283123061977e-11, 1.857434297108983e-10, 1.592233467198178e-11, -1.173771592481677e-10, 1.1665496090537252e-10, 1.2886364193873557e-10, -2.1093389704449506e-10, -2.4675247129314452e-11, 1.515767676711589e-10, -1.2689980450730342e-10, -4.2776899169681866e-11, 1.6317818359826586e-10, -1.4821901477978135e-11, -5.8141610036405774e-11]

    Psat_cheb_coeffs_der = chebder(Psat_cheb_coeffs)
    Psat_coeffs_critical_der = polyder(Psat_coeffs_critical[::-1])[::-1]
    Psat_cheb_constant_factor = (-2.355355160853182, 0.42489124941587103)
#    Psat_cheb_constant_factor = (-19.744219083323905, 0.050649991923423815) # down to .14 Tr
#    Psat_cheb_constant_factor = (-20.25334447874608, 0.049376705093756613) # down to .05
#    Psat_cheb_constant_factor = (-20.88507690836272, 0.0478830941599295) # down to .05 repolishing
#    Psat_cheb_constant_factor = (-51.789209241068214, 0.019310239068163836) # down to .05 with lots of failures C40 only
#    Psat_cheb_constant_factor = (-52.392851049631986, 0.01908689378961204) # down to .03, plenty of failures
#    Psat_cheb_constant_factor = (-52.47770345042524, 0.01905687810661655)

    Psat_cheb_range = (0.003211332390446207, 104.95219556846003)

    phi_sat_coeffs = [4.040440857039882e-09, -1.512382901024055e-07, 2.5363900091436416e-06,
                      -2.4959001060510725e-05, 0.00015714708105355206, -0.0006312347348814933,
                      0.0013488647482434379, 0.0008510254890166079, -0.017614759099592196,
                      0.06640627813169839, -0.13427456425899886, 0.1172205279608668,
                      0.13594473870160448, -0.5560225934266592, 0.7087599054079694,
                      0.6426353018023558]

    _P_zero_l_cheb_coeffs = [0.13358936990391557, -0.20047353906149878, 0.15101308518135467, -0.11422662323168498, 0.08677799907222833, -0.06622719396774103, 0.05078577177767531, -0.03913992025038471, 0.030322206247168845, -0.023618484941949063, 0.018500212460075605, -0.014575143278285305, 0.011551352410948363, -0.00921093058565245, 0.007390713292456164, -0.005968132800177682, 0.00485080886172241, -0.003968872414987763, 0.003269291360484698, -0.002711665819666899, 0.0022651044970457743, -0.0019058978265104418, 0.0016157801830935644, -0.0013806283122768208, 0.0011894838915417153, -0.0010338173333182162, 0.0009069721482541163, -0.0008037443041438563, 0.0007200633946601682, -0.0006527508698173454, 0.0005993365082194993, -0.0005579199462298259, 0.0005270668422661141, -0.0005057321913053223, 0.0004932057251527365, -0.00024453764761005106]
    P_zero_l_cheb_limits = (0.002068158270122966, 27.87515959722943)

    def __init__(self, Tc, Pc, omega, T=None, P=None, V=None):
        self.Tc = Tc
        self.Pc = Pc
        self.omega = omega
        self.T = T
        self.P = P
        self.V = V

        self.b = b = self.c2R*Tc/Pc
        self.a = b*Tc*self.c1R2_c2R
        self.kappa = omega*(-0.26992*omega + 1.54226) + 0.37464
        self.delta, self.epsilon = 2.0*b, -b*b
        self.solve()

    def a_alpha_pure(self, T):
        r'''Method to calculate :math:`a \alpha` for this EOS. Uses the set values of
        `Tc`, `kappa`, and `a`.

        .. math::
            a\alpha = a \left(\kappa \left(- \frac{T^{0.5}}{Tc^{0.5}}
            + 1\right) + 1\right)^{2}

        Parameters
        ----------
        T : float
            Temperature at which to calculate the value, [-]

        Returns
        -------
        a_alpha : float
            Coefficient calculated by EOS-specific method, [J^2/mol^2/Pa]

        Notes
        -----
        This method does not alter the object's state and the temperature
        provided can be a different than that of the object.

        Examples
        --------
        Dodecane at 250 K:

        >>> eos = PR(Tc=658.0, Pc=1820000.0, omega=0.562, T=500., P=1e5)
        >>> eos.a_alpha_pure(250.0)
        15.66839156301
        '''
        x0 = (1.0 + self.kappa*(1.0 - sqrt(T/self.Tc)))
        return self.a*x0*x0

    def a_alpha_and_derivatives_pure(self, T):
        r'''Method to calculate :math:`a \alpha` and its first and second
        derivatives for this EOS. Uses the set values of `Tc`, `kappa`, and `a`.

        .. math::
            a\alpha = a \left(\kappa \left(- \frac{T^{0.5}}{Tc^{0.5}}
            + 1\right) + 1\right)^{2}

        .. math::
            \frac{d a\alpha}{dT} = - \frac{1.0 a \kappa}{T^{0.5} Tc^{0.5}}
            \left(\kappa \left(- \frac{T^{0.5}}{Tc^{0.5}} + 1\right) + 1\right)

        .. math::
            \frac{d^2 a\alpha}{dT^2} = 0.5 a \kappa \left(- \frac{1}{T^{1.5}
            Tc^{0.5}} \left(\kappa \left(\frac{T^{0.5}}{Tc^{0.5}} - 1\right)
            - 1\right) + \frac{\kappa}{T^{1.0} Tc^{1.0}}\right)

        Parameters
        ----------
        T : float
            Temperature at which to calculate the values, [-]

        Returns
        -------
        a_alpha : float
            Coefficient calculated by EOS-specific method, [J^2/mol^2/Pa]
        da_alpha_dT : float
            Temperature derivative of coefficient calculated by EOS-specific
            method, [J^2/mol^2/Pa/K]
        d2a_alpha_dT2 : float
            Second temperature derivative of coefficient calculated by
            EOS-specific method, [J^2/mol^2/Pa/K^2]

        Notes
        -----
        This method does not alter the object's state and the temperature
        provided can be a different than that of the object.

        Examples
        --------
        Dodecane at 250 K:

        >>> eos = PR(Tc=658.0, Pc=1820000.0, omega=0.562, T=500., P=1e5)
        >>> eos.a_alpha_and_derivatives_pure(250.0)
        (15.66839156301, -0.03094091246957, 9.243186769880e-05)
        '''
        # TODO custom water a_alpha?
        # Peng, DY, and DB Robinson. "Two-and Three-Phase Equilibrium Calculations
        # for Coal Gasification and Related Processes,", 1980
        # Thermodynamics of aqueous systems with industrial applications 133 (1980): 393-414.
        # Applies up to Tr .85.
        # Suggested in Equations of State And PVT Analysis.
        Tc, kappa, a = self.Tc, self.kappa, self.a
        x0 = sqrt(T)
        x1 = 1.0/sqrt(Tc)
        x2 = kappa*(x0*x1 - 1.) - 1.
        x3 = a*kappa
        x4 = x1*x2/x0

        a_alpha = a*x2*x2
        da_alpha_dT = x4*x3
        d2a_alpha_dT2 = 0.5*x3*(kappa*x1*x1 - x4)/T

        return a_alpha, da_alpha_dT, d2a_alpha_dT2

    def d3a_alpha_dT3_pure(self, T):
        r'''Method to calculate the third temperature derivative of `a_alpha`.
        Uses the set values of `Tc`, `kappa`, and `a`. This property is not
        normally needed.

        .. math::
            \frac{d^3 a\alpha}{dT^3} = \frac{3 a\kappa \left(- \frac{\kappa}
            {T_{c}} + \frac{\sqrt{\frac{T}{T_{c}}} \left(\kappa \left(\sqrt{\frac{T}
            {T_{c}}} - 1\right) - 1\right)}{T}\right)}{4 T^{2}}

        Parameters
        ----------
        T : float
            Temperature at which to calculate the derivative, [-]

        Returns
        -------
        d3a_alpha_dT3 : float
            Third temperature derivative of coefficient calculated by
            EOS-specific method, [J^2/mol^2/Pa/K^3]

        Notes
        -----
        This method does not alter the object's state and the temperature
        provided can be a different than that of the object.

        Examples
        --------
        Dodecane at 500 K:

        >>> eos = PR(Tc=658.0, Pc=1820000.0, omega=0.562, T=500., P=1e5)
        >>> eos.d3a_alpha_dT3_pure(500.0)
        -9.8038800671e-08
        '''
        kappa = self.kappa
        x0 = 1.0/self.Tc
        T_inv = 1.0/T
        x1 = sqrt(T*x0)
        return -self.a*0.75*kappa*(kappa*x0 - x1*(kappa*(x1 - 1.0) - 1.0)*T_inv)*T_inv*T_inv

    def P_max_at_V(self, V):
        r'''Method to calculate the maximum pressure the EOS can create at a
        constant volume, if one exists; returns None otherwise.

        Parameters
        ----------
        V : float
            Constant molar volume, [m^3/mol]

        Returns
        -------
        P : float
            Maximum possible isochoric pressure, [Pa]

        Notes
        -----
        The analytical determination of this formula involved some part of the
        discriminant, and much black magic.

        Examples
        --------
        >>> e = PR(P=1e5, V=0.0001437, Tc=512.5, Pc=8084000.0, omega=0.559)
        >>> e.P_max_at_V(e.V)
        2247886208.7
        '''
        '''# Partial notes on how this was determined.
        from sympy import *
        P, T, V = symbols('P, T, V', positive=True)
        Tc, Pc, omega = symbols('Tc, Pc, omega', positive=True)
        R, a, b, kappa = symbols('R, a, b, kappa')

        main = P*R*Tc*V**2 + 2*P*R*Tc*V*b - P*R*Tc*b**2 - P*V*a*kappa**2 + P*a*b*kappa**2 + R*Tc*a*kappa**2 + 2*R*Tc*a*kappa + R*Tc*a
        to_subs = {b: thing.b,
                   kappa: thing.kappa,
                   a: thing.a, R: thermo.eos.R, Tc: thing.Tc, V: thing.V, Tc: thing.Tc, omega: thing.omega}
        solve(Eq(main, 0), P)[0].subs(to_subs)
        '''
        try:
            Tc, a, b, kappa = self.Tc, self.a, self.b, self.kappa
        except:
            Tc, a, b, kappa = self.Tcs[0], self.ais[0], self.bs[0], self.kappas[0]
        P_max = (-R*Tc*a*(kappa**2 + 2*kappa + 1)/(R*Tc*V**2 + 2*R*Tc*V*b - R*Tc*b**2 - V*a*kappa**2 + a*b*kappa**2))
        if P_max < 0.0:
            # No positive pressure - it's negative
            return None
        return P_max


    # (V - b)**3*(V**2 + 2*V*b - b**2)*(P*R*Tc*V**2 + 2*P*R*Tc*V*b - P*R*Tc*b**2 - P*V*a*kappa**2 + P*a*b*kappa**2 + R*Tc*a*kappa**2 + 2*R*Tc*a*kappa + R*Tc*a)


    def solve_T(self, P, V, solution=None):
        r'''Method to calculate `T` from a specified `P` and `V` for the PR
        EOS. Uses `Tc`, `a`, `b`, and `kappa` as well, obtained from the
        class's namespace.

        Parameters
        ----------
        P : float
            Pressure, [Pa]
        V : float
            Molar volume, [m^3/mol]
        solution : str or None, optional
            'l' or 'g' to specify a liquid of vapor solution (if one exists);
            if None, will select a solution more likely to be real (closer to
            STP, attempting to avoid temperatures like 60000 K or 0.0001 K).

        Returns
        -------
        T : float
            Temperature, [K]

        Notes
        -----
        The exact solution can be derived as follows, and is excluded for
        breviety.

        >>> from sympy import *
        >>> P, T, V = symbols('P, T, V')
        >>> Tc, Pc, omega = symbols('Tc, Pc, omega')
        >>> R, a, b, kappa = symbols('R, a, b, kappa')
        >>> a_alpha = a*(1 + kappa*(1-sqrt(T/Tc)))**2
        >>> PR_formula = R*T/(V-b) - a_alpha/(V*(V+b)+b*(V-b)) - P
        >>> #solve(PR_formula, T)

        After careful evaluation of the results of the analytical formula,
        it was discovered, that numerical precision issues required several
        NR refinement iterations; at at times, when the analytical value is
        extremely erroneous, a call to a full numerical solver not using the
        analytical solution at all is required.

        Examples
        --------
        >>> eos = PR(Tc=658.0, Pc=1820000.0, omega=0.562, T=500., P=1e5)
        >>> eos.solve_T(P=eos.P, V=eos.V_g)
        500.0000000
        '''
        self.no_T_spec = True
        Tc, a, b, kappa = self.Tc, self.a, self.b, self.kappa
        # Needs to be improved to do a NR or two at the end!
        x0 = V*V
        x1 = R*Tc
        x2 = x0*x1
        x3 = kappa*kappa
        x4 = a*x3
        x5 = b*x4
        x6 = 2.*V*b
        x7 = x1*x6
        x8 = b*b
        x9 = x1*x8
        x10 = V*x4
        thing = (x2 - x10 + x5 + x7 - x9)
        x11 = thing*thing
        x12 = x0*x0
        x13 = R*R
        x14 = Tc*Tc
        x15 = x13*x14
        x16 = x8*x8
        x17 = a*a
        x18 = x3*x3
        x19 = x17*x18
        x20 = x0*V
        x21 = 2.*R*Tc*a*x3
        x22 = x8*b
        x23 = 4.*V*x22
        x24 = 4.*b*x20
        x25 = a*x1
        x26 = x25*x8
        x27 = x26*x3
        x28 = x0*x25
        x29 = x28*x3
        x30 = 2.*x8
        x31 = (6.*V*x27 - 2.*b*x29 + x0*x13*x14*x30 + x0*x19 + x12*x15
               + x15*x16 - x15*x23 + x15*x24 - x19*x6 + x19*x8 - x20*x21
               - x21*x22)
        V_m_b = V - b
        x33 = 2.*(R*Tc*a*kappa)
        x34 = P*x2
        x35 = P*x5
        x36 = x25*x3
        x37 = P*x10
        x38 = P*R*Tc
        x39 = V*x17
        x40 = 2.*kappa*x3
        x41 = b*x17
        x42 = P*a*x3

        # 2.*a*kappa - add a negative sign to get the high temperature solution
        # sometimes it is complex!
#            try:
        root_term = sqrt(V_m_b**3*(x0 + x6 - x8)*(P*x7 -
                                          P*x9 + x25 + x33 + x34 + x35
                                          + x36 - x37))
#            except ValueError:
#                # negative number in sqrt
#                return super(PR, self).solve_T(P, V)

        x100 = 2.*a*kappa*x11*(root_term*(kappa + 1.))
        x101 = (x31*V_m_b*((4.*V)*(R*Tc*a*b*kappa) + x0*x33 - x0*x35 + x12*x38
                     + x16*x38 + x18*x39 - x18*x41 - x20*x42 - x22*x42
                     - x23*x38 + x24*x38 + x25*x6 - x26 - x27 + x28 + x29
                     + x3*x39 - x3*x41 + x30*x34 - x33*x8 + x36*x6
                     + 3*x37*x8 + x39*x40 - x40*x41))
        x102 = -Tc/(x11*x31)

        T_calc = (x102*(x100 - x101)) # Normally the correct root
        if T_calc < 0.0:
            # Ruined, call the numerical method; sometimes it happens
            return super(PR, self).solve_T(P, V, solution=solution)

        Tc_inv = 1.0/Tc

        T_calc_high = (x102*(-x100 - x101))
        if solution is not None and solution == 'g':
            T_calc = T_calc_high
        if True:
            c1, c2 = R/(V_m_b), a/(V*(V+b) + b*V_m_b)

            rt = (T_calc*Tc_inv)**0.5
            alpha_root = (1.0 + kappa*(1.0-rt))
            err = c1*T_calc - alpha_root*alpha_root*c2 - P
            if abs(err/P) > 1e-2:
                # Numerical issue - such a bad solution we cannot converge
                return super(PR, self).solve_T(P, V, solution=solution)

            # Newton step - might as well compute it
            derr = c1 + c2*kappa*rt*(kappa*(1.0 -rt) + 1.0)/T_calc
            if derr == 0.0:
                return T_calc
            T_calc = T_calc - err/derr

            # Step 2 - cannot find occasion to need more steps, most of the time
            # this does nothing!
            rt = (T_calc*Tc_inv)**0.5
            alpha_root = (1.0 + kappa*(1.0-rt))
            err = c1*T_calc - alpha_root*alpha_root*c2 - P
            derr = c1 + c2*kappa*rt*(kappa*(1.0 -rt) + 1.0)/T_calc
            T_calc = T_calc - err/derr

            return T_calc


            c1, c2 = R/(V_m_b), a/(V*(V+b) + b*V_m_b)

            rt = (T_calc_high*Tc_inv)**0.5
            alpha_root = (1.0 + kappa*(1.0-rt))
            err = c1*T_calc_high - alpha_root*alpha_root*c2 - P

            # Newton step - might as well compute it
            derr = c1 + c2*kappa*rt*(kappa*(1.0 -rt) + 1.0)/T_calc_high
            T_calc_high = T_calc_high - err/derr

            # Step 2 - cannot find occasion to need more steps, most of the time
            # this does nothing!
            rt = (T_calc_high*Tc_inv)**0.5
            alpha_root = (1.0 + kappa*(1.0-rt))
            err = c1*T_calc_high - alpha_root*alpha_root*c2 - P
            derr = c1 + c2*kappa*rt*(kappa*(1.0 -rt) + 1.0)/T_calc_high
            T_calc_high = T_calc_high - err/derr





            delta, epsilon = self.delta, self.epsilon
            w0 = 1.0*(delta*delta - 4.0*epsilon)**-0.5
            w1 = delta*w0
            w2 = 2.0*w0

#            print(T_calc, T_calc_high)

            a_alpha_low = a*(1.0 + kappa*(1.0-(T_calc/Tc)**0.5))**2.0
            a_alpha_high = a*(1.0 + kappa*(1.0-(T_calc_high/Tc)**0.5))**2.0

            err_low = abs((R*T_calc/(V-b) - a_alpha_low/(V*V + delta*V + epsilon) - P))
            err_high = abs((R*T_calc_high/(V-b) - a_alpha_high/(V*V + delta*V + epsilon) - P))
#                print(err_low, err_high, T_calc, T_calc_high, a_alpha_low, a_alpha_high)

            RT_low = R*T_calc
            G_dep_low = (P*V - RT_low - RT_low*clog(P/RT_low*(V-b)).real
                        - w2*a_alpha_low*catanh(2.0*V*w0 + w1).real)

            RT_high = R*T_calc_high
            G_dep_high = (P*V - RT_high - RT_high*clog(P/RT_high*(V-b)).real
                        - w2*a_alpha_high*catanh(2.0*V*w0 + w1).real)

#                print(G_dep_low, G_dep_high)
            # ((err_low > err_high*2)) and
            if  (T_calc.imag != 0.0 and T_calc_high.imag == 0.0) or (G_dep_high < G_dep_low and (err_high < err_low)):
                T_calc = T_calc_high

            return T_calc


#            if err_high < err_low:
#                T_calc = T_calc_high

#            for Ti in (T_calc, T_calc_high):
#                a_alpha = a*(1.0 + kappa*(1.0-(Ti/Tc)**0.5))**2.0
#
#
#                # Compute P, and the difference?
#                self.P = float(R*self.T/(V-self.b) - self.a_alpha/(V*V + self.delta*V + self.epsilon)
#
#
#
#                RT = R*Ti
#                print(RT, V-b, P/RT*(V-b))
#                G_dep = (P*V - RT - RT*log(P/RT*(V-b))
#                            - w2*a_alpha*catanh(2.0*V*w0 + w1).real)
#                print(G_dep)
#                if G_dep < G_dep_base:
#                    T = Ti
#                    G_dep_base = G_dep
#            T_calc = T

#            print(T_calc, T_calc_high)


#            T_calc = (-Tc*(2.*a*kappa*x11*sqrt(V_m_b**3*(x0 + x6 - x8)*(P*x7 -
#                                              P*x9 + x25 + x33 + x34 + x35
#                                              + x36 - x37))*(kappa + 1.) -
#                x31*V_m_b*((4.*V)*(R*Tc*a*b*kappa) + x0*x33 - x0*x35 + x12*x38
#                         + x16*x38 + x18*x39 - x18*x41 - x20*x42 - x22*x42
#                         - x23*x38 + x24*x38 + x25*x6 - x26 - x27 + x28 + x29
#                         + x3*x39 - x3*x41 + x30*x34 - x33*x8 + x36*x6
#                         + 3*x37*x8 + x39*x40 - x40*x41))/(x11*x31))
#            print(T_calc2/T_calc)

            # Validation code - although the solution is analytical some issues
            # with floating points can still occur
            # Although 99.9 % of points anyone would likely want are plenty good,
            # there are some edge cases as P approaches T or goes under it.

#            c1, c2 = R/(V_m_b), a/(V*(V+b) + b*V_m_b)
#
#            rt = (T_calc*Tc_inv)**0.5
#            alpha_root = (1.0 + kappa*(1.0-rt))
#            err = c1*T_calc - alpha_root*alpha_root*c2 - P
#
#            # Newton step - might as well compute it
#            derr = c1 + c2*kappa*rt*(kappa*(1.0 -rt) + 1.0)/T_calc
#            T_calc = T_calc - err/derr
#
#            # Step 2 - cannot find occasion to need more steps, most of the time
#            # this does nothing!
#            rt = (T_calc*Tc_inv)**0.5
#            alpha_root = (1.0 + kappa*(1.0-rt))
#            err = c1*T_calc - alpha_root*alpha_root*c2 - P
#            derr = c1 + c2*kappa*rt*(kappa*(1.0 -rt) + 1.0)/T_calc
#            T_calc = T_calc - err/derr
##            print(T_calc)
#            return T_calc

#            P_inv = 1.0/P
#            if abs(err/P) < 1e-6:
#                return T_calc
##            print(abs(err/P))
##            return GCEOS.solve_T(self, P, V)
#            for i in range(7):
#                rt = (T_calc*Tc_inv)**0.5
#                alpha_root = (1.0 + kappa*(1.0-rt))
#                err = c1*T_calc - alpha_root*alpha_root*c2 - P
#                derr = c1 + c2*kappa*rt*(kappa*(1.0 -rt) + 1.0)/T_calc
#
#                T_calc = T_calc - err/derr
#                print(err/P, T_calc, derr)
#                if abs(err/P) < 1e-12:
#                    return T_calc
#            return T_calc


    # starts at 0.0008793111898930736
#    Psat_ranges_low = (0.011527649224138653,
#                       0.15177700441811506, 0.7883172905889053, 2.035659276638337,
#                       4.53501754500169, 10.745446771738406, 22.67639480888016,
#                       50.03388490796283, 104.02786866285064)
    # 2019 Nov
#    Psat_ranges_low = (0.15674244743681393, 0.8119861320343748, 2.094720219302703, 4.960845727141835, 11.067460617890934, 25.621853405705796, 43.198888850643804, 104.02786866285064)
#    Psat_coeffs_low = [[-227953.8193412378, 222859.8202525231, -94946.0644714779, 22988.662866916213, -3436.218010266234, 314.10561626462993, -12.536721169650086, -2.392026378146748, 1.7425442228873158, -1.2062891595039678, 0.9256591091303878, -0.7876053099939332, 0.5624587154041579, -3.3553013976814365, 5.4012350148013866e-14], [0.017979999443171253, -0.1407329351142875, 0.5157655870958351, -1.1824391743389553, 1.9175463304080598, -2.370060249233812, 2.3671981077067543, -2.0211919069051754, 1.5662532616167582, -1.1752554496422438, 0.9211423805826566, -0.7870983088912286, 0.5624192663836626, -3.3552995268181935, -4.056076807756881e-08], [2.3465238783212443e-06, -5.1803023754491137e-05, 0.0005331498955415226, -0.0034021195248914006, 0.015107808977575897, -0.04968952806811015, 0.12578046832772882, -0.25143473221174495, 0.40552536074726614, -0.5443994966086247, 0.6434269285808626, -0.6923484892423339, 0.5390886452491613, -3.3516377955152628, -0.0002734868035272342], [-4.149916661961022e-10, 2.1845922714910234e-08, -5.293093383029167e-07, 7.799519138713084e-06, -7.769053551547911e-05, 0.0005486109959120195, -0.0027872878510967723, 0.010013711509364028, -0.023484350891214936, 0.024784713187904924, 0.04189568427991252, -0.2040017547275196, 0.25395831370937016, -3.2456178797446413, -0.01903130694686439], [5.244405747881219e-16, -1.5454390343008565e-14, -2.0604241377631507e-12, 1.8208689279561933e-10, -7.250743412052849e-09, 1.8247981842001254e-07, -3.226779942705286e-06, 4.21332816427672e-05, -0.00041707954900317614, 0.003173654759907457, -0.01868692125208627, 0.0855653889368932, -0.31035507126284995, -2.6634237299183328, -0.2800897855694018], [-2.1214680302656463e-19, 5.783021422459962e-17, -7.315923275334905e-15, 5.698692571821259e-13, -3.0576045765082714e-11, 1.1975824393534794e-09, -3.540115921441331e-08, 8.052781011110919e-07, -1.424237637885889e-05, 0.00019659116938228988, -0.0021156267397923314, 0.017700252965885416, -0.11593142002481696, -3.013661988282298, 0.01996154251720128], [-2.8970166603270677e-23, 1.694610551839978e-20, -4.467776279776866e-18, 7.096773522723984e-16, -7.632413053542317e-14, 5.906374821509563e-12, -3.4056397726361876e-10, 1.4928364875485495e-08, -5.025465019680778e-07, 1.3027126331371714e-05, -0.00025915855275578494, 0.003928557567224198, -0.04532442889219183, -3.235941699431832, 0.33934709098936366], [-1.0487638177712636e-27, 1.1588074100262264e-24, -5.933272229330526e-22, 1.8676144445612704e-19, -4.0425091708892395e-17, 6.37584823835825e-15, -7.573969719222655e-13, 6.907076002118451e-11, -4.883344880881757e-09, 2.6844313931168583e-07, -1.1443544240867529e-05, 0.0003760349651708502, -0.009520080664949915, -3.464433298845877, 1.0399494170785033]]
    # 2019 Dec 08 #1
#    Psat_ranges_low = ([0.1566663623710075, 0.8122712349481437, 2.0945197784666294, 4.961535043425216, 11.064718660459363, 25.62532893636351, 43.17405809523583, 85.5638421625653, 169.8222874125952)
#    Psat_coeffs_low = [[-6.364470992262544e-23, 1.5661396802352383e-19, -1.788719435685493e-16, 1.2567790299823932e-13, -6.068855158259506e-11, 2.130642024043302e-08, -5.608337854780211e-06, 0.0011243910475529856, -0.17253439771817053, 20.164796917496496, -1766.983966143576, 112571.42973915562, -4928969.89775339, 132767165.35442507, -1659856970.7084315], [-6.755028337063007e-31, 1.2373135465776702e-27, -1.0534911582623026e-24, 5.532082037130418e-22, -2.0042818462405888e-19, 5.3092667094437664e-17, -1.0629813459498251e-14, 1.6396189295145161e-12, -1.9677160870915945e-10, 1.8425759971191095e-08, -1.3425348946576017e-06, 7.562661739651473e-05, -0.0032885862389808195, -3.5452990752336735, 1.5360178058346605], [-5.909795950371768e-27, 5.645060782013921e-24, -2.5062698828832408e-21, 6.861883492029141e-19, -1.2960098086863643e-16, 1.7893963536931406e-14, -1.8669999568680822e-12, 1.5005071785133313e-10, -9.381783948347974e-09, 4.576967837674971e-07, -1.7378660968493725e-05, 0.0005105597560223805, -0.011603105202254462, -3.4447117223858394, 0.9538198797898474], [-2.8780483706946006e-23, 1.4693097909367858e-20, -3.492711723365092e-18, 5.129438453755985e-16, -5.2066819983096923e-14, 3.87131295903126e-12, -2.1797843188384387e-10, 9.475510493050094e-09, -3.212229879279181e-07, 8.520129885652724e-06, -0.00017645941977890718, 0.0028397690069188186, -0.035584878748907235, -3.2889972189483, 0.47227047696507896], [-2.133647784270567e-19, 5.813855761166538e-17, -7.351939324704256e-15, 5.724415520048679e-13, -3.0701524683808055e-11, 1.2020043191332715e-09, -3.5517231986184477e-08, 8.075833591581873e-07, -1.4277180602174389e-05, 0.0001969886336996064, -0.0021190060629508248, 0.017720993486168023, -0.11601827744842373, -3.0134398433062954, 0.019699769017179847], [5.217055552725474e-16, -1.561972494582649e-14, -2.027739589933126e-12, 1.8030004183143271e-10, -7.1961213928967356e-09, 1.8138160781745565e-07, -3.2112101506231723e-06, 4.197218861582643e-05, -0.00041584453068251905, 0.0031666287443832307, -0.018657602063128432, 0.08547811393673718, -0.31017952035114504, -2.6636376461277504, -0.27997050354186115], [-4.1558987320232216e-10, 2.1874838982254277e-08, -5.299524926441045e-07, 7.808241563359814e-06, -7.777110034030892e-05, 0.0005491470176474339, -0.002789936581283384, 0.010023585334231266, -0.023512249664927133, 0.02484416646533969, 0.04180162903589153, -0.20389464760201653, 0.25387532037317434, -3.245578712101638, -0.01903980099778657], [2.3320945490434305e-06, -5.15194336734163e-05, 0.0005305911686609431, -0.003388078003236081, 0.015055473744080193, -0.049549442201717114, 0.12550289037335455, -0.251021291476035, 0.40506041321992375, -0.5440068047537978, 0.6431818377117259, -0.6922389245218481, 0.5390554975784367, -3.3516317236219626, -0.00027399457467680577], [0.017760683349597454, -0.1392342452029993, 0.5111179189769633, -1.1737814955588932, 1.9067391494716879, -2.3605113086814407, 2.361048334775187, -2.0182633656154794, 1.5652184041682835, -1.1749857171593956, 0.92109138142958, -0.7870915307971148, 0.5624186680171368, -3.3552994954150326, -4.130013597780646e-08], [1842638.012244339, -2064103.5077599594, 1029111.4284441478, -300839.92590603326, 57174.96949130112, -7405.305505076668, 668.4504791023379, -43.94219790319933, 3.4634979070792977, -1.2528527563309222, 0.9264289045482768, -0.787612207652486, 0.5624587411994793, -3.3553013976928456, 4.846123502488808e-14]]

    # 2019 Dec 08 #2
#    Psat_ranges_low = (0.15674244743681393, 0.8119861320343748, 2.094720219302703, 4.961535043425216, 11.064718660459363, 25.62532893636351, 43.17405809523583, 85.5638421625653, 169.8222874125952, 192.707581659434)
#    Psat_coeffs_low = [[-393279.9328001248, 414920.88015712175, -194956.1186003408, 53799.692378381624, -9679.442200674115, 1189.1133946984114, -99.38789237175924, 3.7558250389696366, 1.4341105372610397, -1.195532646019414, 0.9254075742030472, -0.7876016031722438, 0.5624586846061402, -3.355301397567417, -2.475797344914099e-14], [0.018200741617324958, -0.14216111513088853, 0.5199706046777292, -1.1898993034816217, 1.9264460624802726, -2.377604380463091, 2.3718790446551283, -2.0233492715449346, 1.5669946704278936, -1.175444344921655, 0.9211774746760774, -0.787102916441927, 0.5624196703434721, -3.3552995479850125, -4.006059328709455e-08], [2.362594082154845e-06, -5.213477214805086e-05, 0.0005363047209564668, -0.0034204334370065157, 0.015180294585886198, -0.04989640532490752, 0.1262194343941631, -0.252138050376706, 0.4063802322466773, -0.5451837881722801, 0.643961448026334, -0.6926108644042617, 0.5391763183580807, -3.3516556444811516, -0.00027181665396192045], [-4.1566510211197074e-10, 2.1878563345656593e-08, -5.30037387599558e-07, 7.809422248533072e-06, -7.77822904769859e-05, 0.0005492234565335112, -0.002790324592151159, 0.010025071882175543, -0.023516568419967406, 0.024853633218471893, 0.04178621870041742, -0.20387658476895476, 0.2538609101701838, -3.2455717084245443, -0.019041365569938407], [5.952860605957254e-16, -2.3560872386568428e-14, -1.6328974906691505e-12, 1.6831386671561567e-10, -6.947967158882692e-09, 1.77675502929117e-07, -3.170039732850266e-06, 4.162662881336586e-05, -0.0004136425496617131, 0.0031560285189308705, -0.018619655683130842, 0.085380163769752, -0.3100071777702119, -2.6638226631426187, -0.279879068340815], [-2.1336825570293267e-19, 5.813946215182557e-17, -7.352047876443287e-15, 5.724495165386215e-13, -3.0701923762367554e-11, 1.2020187632285275e-09, -3.5517621350872006e-08, 8.075912994222895e-07, -1.4277303680626562e-05, 0.00019699007656794466, -0.00211901865445771, 0.01772107279538477, -0.1160186182468458, -3.0134389491023668, 0.019698688209032866], [-2.8780483706946006e-23, 1.4693097909367858e-20, -3.492711723365092e-18, 5.129438453755985e-16, -5.2066819983096923e-14, 3.87131295903126e-12, -2.1797843188384387e-10, 9.475510493050094e-09, -3.212229879279181e-07, 8.520129885652724e-06, -0.00017645941977890718, 0.0028397690069188186, -0.035584878748907235, -3.2889972189483, 0.47227047696507896], [-5.909795950371768e-27, 5.645060782013921e-24, -2.5062698828832408e-21, 6.861883492029141e-19, -1.2960098086863643e-16, 1.7893963536931406e-14, -1.8669999568680822e-12, 1.5005071785133313e-10, -9.381783948347974e-09, 4.576967837674971e-07, -1.7378660968493725e-05, 0.0005105597560223805, -0.011603105202254462, -3.4447117223858394, 0.9538198797898474], [-6.755028337063007e-31, 1.2373135465776702e-27, -1.0534911582623026e-24, 5.532082037130418e-22, -2.0042818462405888e-19, 5.3092667094437664e-17, -1.0629813459498251e-14, 1.6396189295145161e-12, -1.9677160870915945e-10, 1.8425759971191095e-08, -1.3425348946576017e-06, 7.562661739651473e-05, -0.0032885862389808195, -3.5452990752336735, 1.5360178058346605], [-6.364470992262544e-23, 1.5661396802352383e-19, -1.788719435685493e-16, 1.2567790299823932e-13, -6.068855158259506e-11, 2.130642024043302e-08, -5.608337854780211e-06, 0.0011243910475529856, -0.17253439771817053, 20.164796917496496, -1766.983966143576, 112571.42973915562, -4928969.89775339, 132767165.35442507, -1659856970.7084315]]
    # 2019 Dec 08 #3
    Psat_ranges_low = (0.038515189998761204, 0.6472853332269844, 2.0945197784666294, 4.961232873814024, 11.067553885784903, 25.624838497870584, 43.20169529076582, 85.5588271726612, 192.72834691988226)
    Psat_coeffs_low = [[2338676895826482.5, -736415034973095.6, 105113277697825.1, -8995168780410.754, 514360029044.81494, -20734723655.83978, 605871516.8891307, -12994014.122638363, 204831.11357912835, -2351.9913154464143, 18.149657683324232, 0.8151930684866298, -0.7871881357728392, 0.5624577476810062, -3.35530139647672, -4.836964162535651e-13], [-0.13805715433070773, 0.8489231609102119, -2.450329797856018, 4.447856574793218, -5.767299107094559, 5.794674157897756, -4.825296555657044, 3.5520183799445926, -2.4600869594916634, 1.6909163275418595, -1.2021498414235525, 0.9254639369127162, -0.7875982246546266, 0.5624585116206676, -3.3553013938160787, -3.331224185387782e-11], [-2.3814071133383825e-06, 5.318261908739265e-05, -0.0005538990617858645, 0.0035761255785055936, -0.016054997425247523, 0.05333504500541739, -0.13636391080337568, 0.27593424749870343, -0.4517901507372948, 0.6114112167354924, -0.7059858408782421, 0.7385376731146207, -0.7329884294338728, 0.5509890744823249, -3.353773232516225, -9.646546737407391e-05], [2.6058661808460023e-11, -1.75914103924121e-09, 5.396299167286894e-08, -1.0007922530068192e-06, 1.2554484077194732e-05, -0.0001125821062183067, 0.0007410322067253991, -0.0035992993229111833, 0.012657105041028169, -0.030121969848977304, 0.03753504314148813, 0.02349666014556937, -0.18469580367455368, 0.24005237728233714, -3.239469690554324, -0.020289142467969867], [-1.082394018559102e-15, 1.2914854481231322e-13, -7.104839518580019e-12, 2.3832489222439473e-10, -5.425087002560749e-09, 8.804418548276272e-08, -1.0364065054630989e-06, 8.719985338278278e-06, -4.8325538208084174e-05, 0.00011200959608941485, 0.0008028675551716892, -0.010695106054891056, 0.06594801536296582, -0.27725262867260253, -2.6977571369079514, -0.2635895959694814], [1.1488824622125947e-20, -3.331154652317046e-18, 4.503372697637035e-16, -3.7684497582121125e-14, 2.1852058912840643e-12, -9.313780852814459e-11, 3.019939074381905e-09, -7.605074783395472e-08, 1.5052679183948458e-06, -2.354701523431422e-05, 0.00029127690705745875, -0.0028399757838276493, 0.02173245057169364, -0.13135011490812692, -2.9774476427885146, -0.01942256817236654], [1.0436558787976772e-24, -5.473723131383567e-22, 1.3452696879486453e-19, -2.0573736968717295e-17, 2.1924486360657888e-15, -1.7272619586846295e-13, 1.0413985148866247e-11, -4.906312890258065e-10, 1.8279149292524938e-08, -5.414588408693672e-07, 1.275367009914141e-05, -0.00023786604002741, 0.0034903075344121025, -0.04033658323380905, -3.2676007023496245, 0.42749816097639837], [9.060766533667912e-29, -9.196819760777788e-26, 4.3601925662975664e-23, -1.2818245897574232e-20, 2.615903295904718e-18, -3.930631843509798e-16, 4.500311702777485e-14, -4.007582103109645e-12, 2.808196479352211e-10, -1.5562164421777763e-08, 6.818206236433737e-07, -2.350273523243411e-05, 0.0006326097721162514, -0.013277937187152783, -3.4305615375066876, 0.8983326523220114], [1.1247677438654667e-33, -2.4697583969349065e-30, 2.5286510080356973e-27, -1.6024926981128421e-24, 7.03655740810716e-22, -2.2705238015446456e-19, 5.57121222696514e-17, -1.0609879702627998e-14, 1.5863699537553053e-12, -1.8713657213281574e-10, 1.7407548458856668e-08, -1.2702047168798462e-06, 7.210856106809965e-05, -0.0031754110755806966, -3.5474790036315795, 1.555110704923493]]


if __name__ == "__main__":

    eos = PR(Tc=507.6, Pc=3025000.0, omega=0.2975, T=400., P=1E6)

    print( 'eos.V_l, eos.V_g', eos.V_l, eos.V_g, 'm^3/mol')
    print( 'eos.rho_l, eos.rho_g', eos.rho_l, eos.rho_g )

    e2 = PR(Tc=507.6, Pc=3025000.0, omega=0.2975, T=440., P=1E6)
    print( 'eos.V_l, eos.V_g', e2.V_l, e2.V_g, 'm^3/mol')
    print( 'eos.rho_l, eos.rho_g', e2.rho_l, e2.rho_g )
    print()
    print( dir(e2) )
