import numpy as np
import json
import warnings
from pathlib import Path
from figaro.load import load_data as load_data_figaro, load_density as load_density_figaro, save_density as save_density_figaro
from anubis.utils import get_samples_and_weights, get_labels
from anubis.exceptions import ANUBISException
from anubis.mixture import het_mixture, par_model, nonpar_model

def save_density(draws, models, folder = '.', name = 'density'):
    """
    Exports a list of anubis.mixture.het_mixture instances and the corresponding samples to file

    Arguments:
        :list draws:                   list of mixtures to be saved
        :str or Path folder:           folder in which the output file will be saved
        :str name:                     name to be given to output file
        :list-of-str pars_labels:      labels for parameters
        :list-of-str par_model_labels: labels for models (for weights)
    """
    samples = get_samples_and_weights(draws)
    labels  = get_labels(draws, 'save', models)
    dict_info = {'augment': draws[0].augment,
                 'probit': draws[0].probit,
                 'bounds': draws[0].bounds.tolist(),
                 'hierarchical': draws[0].hierarchical,
                 'n_shared_pars': draws[0].n_shared_pars,
                }
    # Save samples
    np.savetxt(Path(folder, name+'_samples.txt'), samples, header = ' '.join(labels))
    # Save mixture info
    with open(Path(folder, name+'_info.json'), 'w') as f:
        json.dump(json.dumps(dict_info), f)
    # Save non-parametric model
    if draws[0].augment:
        mixtures = [d.models[0].mixture for d in draws]
        save_density_figaro(draws, folder, name+'_nonpar', ext = 'json')
    # Save alpha factors
    if draws[0].selfunc is not None:
        alphas = np.array([[m.alpha for m in d.models] for d in draws])
        np.savetxt(Path(folder, name+'_alphas.txt'), alphas, header = ' '.join(labels[:-len(d.models[0])]))
    
def load_density(models, selection_function = None, name = 'density', path = '.', make_comp = True):
    """
    Loads a list of anubis.mixture.het_mixture instances from path.

    Arguments:
        :str or Path path: path with draws (file or folder)

    Returns
        :list: anubis.het_mixture object instances
    """
    path = Path(path).resolve()
    file_samples = Path(path, name+'_samples.txt')
    file_info    = Path(path, name+'_info.json')
    try:
        with open(file_info, 'r') as fjson:
            info = json.loads(json.load(fjson))
        samples = np.genfromtxt(file_samples, names = True)
        if info['augment']:
            file_nonpar  = Path(path, name+'_nonpar.json')
            nonpar_draws = load_density_figaro(file_nonpar, make_comp = True)
        if selection_function is not None:
            file_alphas = Path(path, name+'_alphas.txt')
            alphas = np.genfromtxt(file_alphas, names = True)
        else:
            ai = np.ones(len(models) + augment)
            alphas = {model['name']: ai for model in models}
            if info['augment']:
                alphas['np'] = ai
    except FileNotFoundError:
        raise ANUBISException("{0} files not found. Please provide them or re-run the inference.".format(name))
    info['bounds'] = np.atleast_2d(info['bounds'])
    # Join list of parameter names
    for model in models:
        try:
            model['all_par_names'] = np.concatenate((model['par_names'], model['shared_par_names']))
        except KeyError:
            model['all_par_names'] = model['par_names']
        model['samples'] = np.array([samples[l] for l in model['all_par_names']])
    # Weights
    weight_labels = ['w_{}'.format(model['name']) for model in models]
    if info['augment']:
        weight_labels = ['w_np'] + weight_labels
    weights = np.array([samples[w] for w in weight_labels])
    # Build draws
    draws = []
    for i in range(len(samples)):
        mix_models = []
        if info['augment']:
            np = nonpar_model(mixture            = nonpar_draws[i],
                              hierarchical       = info['hierarchical'],
                              selection_function = selection_function,
                              )
            mix_models.append(np)
        for model in models:
            m = par_model(model              = model['model'],
                          pars               = model['samples'][i],
                          bounds             = info['bounds'],
                          probit             = info['probit'],
                          hierarchical       = info['hierarchical'],
                          selection_function = selection_function,
                          norm               = alphas[model['name']][i],
                          )
            mix_models.append(m)
        hmix = het_mixture(models        = mix_models,
                           weights       = weights[i],
                           bounds        = info['bounds'],
                           augment       = info['augment'],
                           hierarchical  = info['hierarchical'],
                           selfunc       = selection_function,
                           n_shared_pars = info['n_shared_pars'],
                           )
        draws.append(hmix)
    return draws

def load_data(path_samples, path_mixtures, *args, **kwargs):
    """
    Loads the data from .txt files (for simulations) or .h5/.hdf5/.dat files (posteriors from GWTC-x) along with their DPGMM reconstruction (must be available in advance).
    Default cosmological parameters from Planck Collaboration (2021) in a flat Universe (https://www.aanda.org/articles/aa/pdf/2020/09/aa33910-18.pdf)
    Not all GW parameters are implemented: run figaro.load.available_gw_pars() for a list of available parameters.
    
    Arguments:
        str or Path path_samples:  folder with samples files
        str or Path path_mixtures: folder with mixtures files
        bool seed:                 fixes the seed to a default value (1) for reproducibility
        list-of-str par:           list with parameter(s) to extract from GW posteriors
        int n_samples:             number of samples for (random) downsampling. Default -1: all samples
        double h:                  Hubble constant H0/100 [km/(s*Mpc)]
        double om:                 matter density parameter
        double ol:                 cosmological constant density parameter
        str waveform:              waveform family to be used ('combined', 'seob', 'imr')
        double snr_threhsold:      SNR threshold for event filtering. For injection analysis only.
        double far_threshold:      FAR threshold for event filtering. For injection analysis only.
        bool verbose:              show progress bar

    Returns:
        iterable:   iterable storing samples and reconstructions
        np.ndarray: names
    """
    samples, names = load_data_figaro(path_samples, *args, **kwargs)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=UserWarning)
        mixtures = [load_density_figaro(Path(path_mixtures, 'draws_'+ev+'.json'), make_comp = False) for ev in names]
    return [[ss, mm] for ss, mm in zip(samples, mixtures)], names
