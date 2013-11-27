import os
import logging
import functools

import scipy
import sklearn
import numpy as np

import logistic

def read_swissprot_data():
    """Reads in swissprot dataset from 3 files in proteindata folder.
        Returns 3-tuple of numpy arrays.
    """
    folder = 'proteindata'
    npy_filenames = 'pos', 'neg', 'test_pos'
    return (np.load(os.path.join(folder, 'data.%s.swissprot.npy' % d)) for d in npy_filenames)

def create_labels(*stacks):
    """Accepts a variable number of of 2-tuples, where the first element is a 0 or 1 label,
        and the second element is the number of such labels to append.
       Returns a 1-d array with lots of 0's and 1's in sequence.
    """
    labels = [np.array([label] * number) for label, number in stacks]
    return np.hstack(labels)

def calculate_roc(true_labels, estimated_labels):
    """Accepts two 1-d arrays of the same size.
       Returns the false positive rate array, true positive rate array (for graphic ROC),
            and the area under the ROC curve.
    """
    fpr, tpr, _ = sklearn.metrics.roc_curve(true_labels, estimated_labels)
    roc_auc = sklearn.metrics.auc(fpr, tpr)
    return fpr, tpr, roc_auc

def svm_label_data(train_set, train_labels, test_set, C=1000.0, positive_weight=1.0, sample_weight=None):
    c = sklearn.svm.SVC(C=C, class_weight={0: 1.0, 1: positive_weight})
    c.probability = True
    c.fit(train_set, train_labels, sample_weight=sample_weight)
    svm_labels = c.predict_proba(test_set)
    return svm_labels

if __name__=='__main__':
    FORMAT = '%(asctime)-15s %(message)s'
    logging.basicConfig(format=FORMAT, level=logging.DEBUG)

    max_key = 24081

    pos, neg, unlabeled_pos = read_swissprot_data()

    # Use less data so that we can move faster, comment this out to use full dataset
    #truncate = lambda m: m[:int(m.shape[0] / 10),:]
    #pos, neg, unlabeled_pos = truncate(pos), truncate(neg), truncate(unlabeled_pos)

    num_folds = 10
    kfold_pos = list(sklearn.cross_validation.KFold(pos.shape[0], k=num_folds, shuffle=True, random_state=0))
    kfold_neg = list(sklearn.cross_validation.KFold(neg.shape[0], k=num_folds, shuffle=True, random_state=0))
    kfold_unlabeled_pos = list(sklearn.cross_validation.KFold(unlabeled_pos.shape[0], k=num_folds, shuffle=True, random_state=0))

    for i in range(1):
        pos_indices_train, pos_indices_test = kfold_pos[i]
        neg_indices_train, neg_indices_test = kfold_neg[i]
        unlabeled_pos_indices_train, unlabeled_pos_indices_test = kfold_unlabeled_pos[i]

        pos_train, pos_test = pos[pos_indices_train], pos[pos_indices_test]
        neg_train, neg_test = neg[neg_indices_train], neg[neg_indices_test]
        unlabeled_pos_train, unlabeled_pos_test = unlabeled_pos[unlabeled_pos_indices_train], unlabeled_pos[unlabeled_pos_indices_test]

        test_set = np.vstack([pos_test, unlabeled_pos_test, neg_test])
        test_labels = create_labels((1, pos_test.shape[0] + unlabeled_pos_test.shape[0]),
                                    (0, neg_test.shape[0]))

        logging.debug('pos train', pos_train.shape)
        logging.debug('neg train', neg_train.shape)
        logging.debug('unlabeled pos train', unlabeled_pos_train.shape)

        # set up the datasets
        X = np.vstack([pos_train, unlabeled_pos_train, neg_train])
        y = create_labels((1, pos_train.shape[0]),
                          (0, unlabeled_pos_train.shape[0] + neg_train.shape[0]))
        y_labeled = create_labels((1, pos_train.shape[0] + unlabeled_pos_train.shape[0]),
                                  (0, neg_train.shape[0]))
        X, y, y_labeled = sklearn.utils.shuffle(X, y, y_labeled)
        X = scipy.sparse.csr_matrix(X) # sparsify X

        # Baseline if we knew everything
        max_iter = 100
        logging.info('starting LR on totally labeled data...')
        theta_labeled = logistic.fast_logistic_gradient_descent(X,
                                                                y_labeled,
                                                                max_iter=max_iter)
        logging.info('done LR')

        # calculate the parameters
        logging.info('starting LR on pos-only data...')
        thetaR = logistic.fast_logistic_gradient_descent(X,
                                                         y,
                                                         max_iter=max_iter)
        logging.info('done LR')
        logging.info('starting modified LR on pos-only data...')
        thetaMR, b = logistic.fast_modified_logistic_gradient_descent(X,
                                                                      y, 
                                                                      max_iter=max_iter, 
                                                                      alpha=0.01)
        logging.info('done modified LR on pos-only data')


        # label the test set
        baseline_labels = logistic.label_data(test_set, theta_labeled, binarize=False)
        regression_labels = logistic.label_data(test_set, thetaR, binarize=False)
        modified_regression_labels = logistic.label_data(test_set, thetaMR, (b * b), binarize=False)

        calculate_test_roc = functools.partial(calculate_roc, test_labels)

        roc_curves = []

        # Compute ROC curve and area the curve
        fpr, tpr, roc_auc = calculate_test_roc(baseline_labels)
        name = 'LR true labels'
        roc_curves.append((name, roc_auc, fpr, tpr, 'r-'))
        logging.info('AUC for %s: %f' % (name, roc_auc))

        # Compute ROC curve and area the curve
        fpr, tpr, roc_auc = calculate_test_roc(regression_labels)
        name = 'LR pos-only labels'
        roc_curves.append((name, roc_auc, fpr, tpr, 'r-.'))
        logging.info('AUC for %s: %f' % (name, roc_auc))

        # Compute ROC curve and area the curve
        fpr, tpr, roc_auc = calculate_test_roc(modified_regression_labels)
        name = 'Modified LR pos-only labels'
        roc_curves.append((name, roc_auc, fpr, tpr, 'r--'))
        logging.info('AUC for %s: %f' % (name, roc_auc))

        logging.info('starting SVM on pos-only data...')
        svm_labels = svm_label_data(X, y, test_set, C=1000.0)
        fpr, tpr, roc_auc = calculate_test_roc(svm_labels[:,1])
        name = 'SVM pos-only labels'
        roc_curves.append((name, roc_auc, fpr, tpr, 'b-.'))
        logging.info('AUC for %s: %f' % (name, roc_auc))
        logging.info('done SVM')

        logging.info('starting Biased SVM...')
        svm_labels = svm_label_data(X, y, test_set, C=1000.0, positive_weight=0.00001)
        fpr, tpr, roc_auc = calculate_test_roc(svm_labels[:,1])
        name = 'Biased SVM pos-only labels'
        roc_curves.append((name, roc_auc, fpr, tpr, 'g-'))
        logging.info('AUC for %s: %f' % (name, roc_auc))

        logging.info('starting weighted SVM...')
        # I have to copy to avoid an error that says that svm_weight is not C-contiguous!
        svm_weight = svm_label_data(X, y, X, C=1000.0)[:,1].copy()
        # now run this again with the probabilites as the weights
        svm_labels = svm_label_data(X, y, test_set, C=1000.0, sample_weight=svm_weight)
        fpr, tpr, roc_auc = calculate_test_roc(svm_labels[:,1])
        name = 'Weighted SVM pos-only labels'
        roc_curves.append((name, roc_auc, fpr, tpr, 'g--'))
        logging.info('AUC for %s: %f' % (name, roc_auc))

        logging.info('starting SVM on true labels...')
        svm_labels = svm_label_data(X, y_labeled, test_set, C=1000.0)
        fpr, tpr, roc_auc = calculate_test_roc(svm_labels[:,1])
        name = 'SVM true labels'
        roc_curves.append((name, roc_auc, fpr, tpr, 'b-'))
        logging.info('AUC for %s: %f' % (name, roc_auc))

        # Plot ROC curve
        import pylab as pl
        pl.clf()

        sorted_roc_curves = reversed(sorted(roc_curves, key=lambda a: a[1]))
        for (name, roc_auc, fpr, tpr, color) in sorted_roc_curves:
            pl.plot(fpr, tpr, color, label='%s (AUC = %0.4f)' % (name, roc_auc))

        pl.plot([0, 1], [0, 1], 'k--')
        pl.xlim([0.0, 0.3])
        pl.ylim([0.7, 1.0])
        pl.xlabel('False Positive Rate')
        pl.ylabel('True Positive Rate')
        pl.title('Receiver operating characteristic example')
        pl.legend(loc="lower right")
        pl.show()


